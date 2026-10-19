"""ACME Bank web app: the page of the bank and its commands, and the backend it talks to (same origin, no CORS).

The browser holds no token or key of its own: an opaque id in an HttpOnly cookie, nothing more. The tokens of the people who signed in (each at Access
Management's own login page, with the authorization code flow and PKCE), the key of the Developers plan and the keys of the teams stay in this process; the
one place a token is shown is the Tokens drawer, to the user it belongs to, when they open it.
"""
import asyncio
import contextlib
import logging
import time
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

import commands
import hops
import llm
import money
from am import AccessManagement
from answers import Answers
from apis import Apis
from bounds import SPAN, moment
from chat import MAX_MESSAGE, Chat
from claims import jwt_claims
from evidence import FOUND, MISSING, BadItem, Evidence, parse as parse_item
from links import Links
from management import Management
from people import PERSONAS, TEAMS, Persona, by_username, describe
from presenter import Presenter
from security import Guard
from sessions import NotSignedIn, Session, Sessions
from settings import ConfigError, Settings
from sign_in import SignIns
from teams import PROMPTS, TeamKeys, Teams
from upstream import Clients, UpstreamError

log = logging.getLogger("bank-web")

COOKIE = "acme_sid"
SESSION_SECONDS = 8 * 3600
# Generic questions without a digit, which the semantic cache may answer, far enough apart for it to tell them apart: each
# press of the page's FAQ button takes the next one, so the first answer of the two always comes from the model
FAQS = ("What is a savings account?", "What is a credit score?", "How does compound interest work?", "What is an overdraft?",
        "What is a direct debit?", "What is a joint account?", "What does a bank teller do?", "What is a debit card?")
# A long answer is 500-800 tokens. The gateway counts a call after it is made, so ten of these pass the 3,000 tokens
# per minute of the Developers plan with room to spare; with 300 the tenth call is still let through.
DEVELOPER_MAX_TOKENS = 600
PRESENTER_ACTIONS = ("pause", "resume")
OUTCOMES = ("signed-in", "refused", "expired", "other", "stranger", "failed")      # how a sign-in ends, as the page of the window says it (static/js/words.js has the sentences)


class BadRequest(Exception):
    pass


class Web:
    def __init__(self, settings: Settings, clients: Clients):
        self.settings, self.clients = settings, clients
        self.static = Path(__file__).parent / "static"
        self.sessions = Sessions(ttl=SESSION_SECONDS)
        self.signins = SignIns()
        self.links = Links(settings.gamma_url, settings.apim_env)
        self.am = AccessManagement(clients.am, settings)
        self.chat = Chat(clients, settings, self.am)
        management = Management(clients.gamma, settings)
        self.keys = TeamKeys(management)
        self.teams = Teams(clients.gateway, settings, self.keys, self.links)
        self.apis = Apis(management)
        self.answers = Answers()
        self.evidence = Evidence(management, self.apis, self.workspace_id, self.links)
        self.presenter = Presenter(clients, settings, self.am, self.chat, management, self.keys, self.sessions)

    # -- helpers ---------------------------------------------------------------------------------------------------
    def current(self, request: Request) -> Session | None:
        return self.sessions.get(request.cookies.get(COOKIE, ""))

    def signed_in(self, request: Request) -> Session:
        session = self.current(request)
        if session is None or session.persona is None:
            raise NotSignedIn("Sign in first")
        return session

    @staticmethod
    async def body(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError as e:
            raise BadRequest("The request is not JSON") from e
        if not isinstance(body, dict):
            raise BadRequest("The request is not a JSON object")
        return body

    @staticmethod
    def text(body: dict, key: str, limit: int = MAX_MESSAGE) -> str:
        value = body.get(key)
        if not isinstance(value, str) or not value.strip():
            raise BadRequest(f"{key} is empty")
        if len(value) > limit:
            raise BadRequest(f"{key} is longer than {limit} characters")
        return value.strip()

    @staticmethod
    def gateway_on(body: dict) -> bool:
        mode = body.get("gateway", "on")
        if mode not in ("on", "off"):
            raise BadRequest("gateway is on or off")
        return mode == "on"

    @staticmethod
    def who(session: Session | None) -> dict:
        """Who asks now, and everybody who is signed in here (the page switches to one of them without a sign-in, and signs another in at the login page)."""
        signed = [p for p in PERSONAS if session is not None and p in session.signed]
        if session is None or session.persona is None:
            return {"persona": None, "signed": signed}
        return {"persona": session.persona.id, "name": session.persona.name, "role": session.persona.role, "signed": signed}

    # -- page -------------------------------------------------------------------------------------------------------
    async def health(self, request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def config(self, request: Request) -> JSONResponse:
        return JSONResponse({"gamma_url": self.settings.gamma_url, "pages": self.links.pages()})

    async def commands(self, request: Request) -> JSONResponse:
        return JSONResponse({"groups": commands.describe(), "budget_calls": commands.BUDGET_CALLS})

    async def personas(self, request: Request) -> JSONResponse:
        """The three people, with the demo user name and password of each: the login page of Access Management asks for the password (the user name is filled in)."""
        return JSONResponse([{**describe(p), "username": p.username, "password": self.settings.demo_password} for p in PERSONAS.values()])

    # -- session ----------------------------------------------------------------------------------------------------
    async def session(self, request: Request) -> JSONResponse:
        return JSONResponse(self.who(self.current(request)))

    @staticmethod
    def remember(response: Response, request: Request, sid: str) -> Response:
        # Lax, not Strict: a sign-in comes back from Access Management with a navigation of another site (or of another port), and its cookie has to come with it
        response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", path="/", max_age=SESSION_SECONDS,
                            secure=request.url.scheme == "https")
        return response

    async def choose(self, request: Request) -> JSONResponse:
        """Another person asks, one who is signed in here already: no sign-in, no login page."""
        asked = (await self.body(request)).get("persona", "")
        persona = PERSONAS.get(asked) if isinstance(asked, str) else None
        if persona is None:
            raise BadRequest("Unknown user")
        session = self.current(request)
        if session is None or persona.id not in session.signed:
            raise NotSignedIn(f"{persona.first} is not signed in.", persona)
        session.choose(persona)
        return JSONResponse(self.who(session))

    async def sign_out(self, request: Request) -> JSONResponse:
        """The tokens of everybody signed in here are forgotten. Access Management keeps its own session, which a sign-in never trusts (it shows its form)."""
        self.sessions.close(request.cookies.get(COOKIE, ""))
        response = JSONResponse(self.who(None))
        response.delete_cookie(COOKIE, path="/")
        return response

    async def login(self, request: Request) -> Response:
        """The popup of a sign-in lands here: the browser is sent to Access Management's login page, with a `state`, the PKCE challenge, the person's user name as the
        hint and `prompt=login`. Only one of the three people can be asked for, so there is nothing for a link to make this redirect to."""
        persona = PERSONAS.get(request.query_params.get("persona", ""))
        if persona is None:
            raise BadRequest("Unknown user")
        sid = request.cookies.get(COOKIE, "")
        if self.sessions.get(sid) is None:
            sid, _ = self.sessions.open()
        redirect_uri = f"{request.url.scheme}://{request.headers['host']}/callback"      # this page's own address: the browser comes back to where it left
        state, challenge = self.signins.begin(sid, persona.id, redirect_uri)
        response = RedirectResponse(self.am.authorize_url(state=state, challenge=challenge, redirect_uri=redirect_uri, persona=persona), status_code=302)
        return self.remember(response, request, sid)

    async def callback(self, request: Request) -> Response:
        """Where Access Management sends the browser back: the sign-in is checked and finished here, and the window is sent on to the small page that tells the page
        that opened it (nothing of the sign-in stays in its address: the code is used, and the page says only how it ended)."""
        found = request.query_params
        outcome = await self.finish(request, found.get("state", ""), found.get("code", ""), found.get("error"))
        return RedirectResponse(f"/sign-in-done.html?outcome={outcome}", status_code=303)

    async def finish(self, request: Request, state: str, code: str, error: str | None) -> str:
        """How a sign-in that came back ended, one of OUTCOMES. The `state` is taken once, whatever it was worth; it must be one this browser started; the code is
        exchanged here with the verifier that never left; and the tokens are kept for the person who signed in, if that is who was asked for."""
        pending = self.signins.take(state)
        session = self.current(request)
        if pending is None or session is None or pending.sid != request.cookies.get(COOKIE, ""):
            return "expired"
        if error is not None or not code or len(code) > 2048:
            return "refused"
        try:
            tokens = await self.am.exchange(code, pending.verifier, pending.redirect_uri)
        except UpstreamError as e:
            log.warning("sign-in: %s", e.message)
            return "failed"
        who = by_username(jwt_claims(tokens.access_token).get("username"))
        if who is None:
            return "stranger"
        if who.id != pending.persona:
            return "other"
        session.sign_in(who, tokens)
        log.info("sign-in %s", who.id)
        return "signed-in"

    async def tokens(self, request: Request) -> JSONResponse:
        """The claims of the user's token and of the delegated token Ace got for the last question (display only)."""
        session = self.signed_in(request)
        token = await self.am.valid_token(session)
        return JSONResponse({"user": jwt_claims(token), "delegated": session.delegated_claims})

    async def token(self, request: Request) -> JSONResponse:
        """The user's own access token, for the Tokens drawer: what a client of the gateway needs (an MCP client, curl). A POST,
        so that only this page can ask; it goes to the signed-in user and into no log."""
        return JSONResponse({"access_token": await self.am.valid_token(self.signed_in(request))})

    # -- chat and money ---------------------------------------------------------------------------------------------
    async def ask_ace(self, request: Request) -> JSONResponse:
        session, body = self.signed_in(request), await self.body(request)
        turn = await self.turn(request, session, self.text(body, "message"), self.gateway_on(body))
        # who answered: the session cookie is shared by the tabs of a browser, and another tab may have chosen somebody else
        return JSONResponse({**self.answers.turn(turn), "who": self.who(session)})

    async def turn(self, request: Request, session: Session, message: str, gateway_on: bool) -> dict:
        try:
            return await self.chat.turn(session, message, gateway_on)
        except UpstreamError as e:
            if e.status == 401 and session.persona is not None:        # the gateway refused the token: it is of no use, and the person signs in again
                session.forget(session.persona)
            raise

    async def send_money(self, request: Request) -> JSONResponse:
        session, body = self.signed_in(request), await self.body(request)
        try:
            arguments = money.parse(body)
        except money.BadTransfer as e:
            raise BadRequest(str(e)) from e
        on = self.gateway_on(body)
        token = await self.am.valid_token(session) if on else None
        result = await money.send(self.clients.gateway if on else self.clients.internal,
                                  self.settings.mcp_url if on else self.settings.mcp_direct_url,
                                  token, arguments, session.persona, gateway=on)
        log.info("send-money %s gateway=%s %s", session.persona.id, "on" if on else "off", result["word"])
        return JSONResponse({**self.answers.payment(result), "who": self.who(session)})

    async def run_command(self, request: Request) -> JSONResponse:
        """One command of the page that asks Ace or moves money: as the person it is for, with that person's token if this browser holds it, and without a token if it
        does not. A command signs nobody in: that is the person control's job. It answers like `/api/chat` or `/api/send-money`, with who answered. What the platform
        made of it is read in Gamma, not here."""
        command = commands.COMMANDS.get(request.path_params["command"])
        if command is None:
            raise HTTPException(404, "Unknown command")
        if command.kind == commands.BUDGET:
            raise BadRequest("This command spends the budget of a team: it asks the team's route")
        persona, session = PERSONAS[command.persona], self.current(request)
        if session is None or persona.id not in session.signed:
            return await self.without_token(request, command, persona)
        session.choose(persona)
        if command.kind == commands.CHAT:
            found = self.answers.turn(await self.turn(request, session, command.message, not command.direct))
        else:
            arguments = money.parse(command.transfer)
            token = await self.am.valid_token(session)
            found = self.answers.payment(await money.send(self.clients.gateway, self.settings.mcp_url, token, arguments, persona, gateway=True))
        log.info("command %s gateway=%s", command.id, "off" if command.direct else "on")
        return JSONResponse({**found, "who": self.who(session)})

    async def without_token(self, request: Request, command: commands.Command, persona: Persona) -> JSONResponse:
        """The command of somebody this browser holds no token for, sent as it is, with no token: the gateway's OAuth2 plan refuses it with a 401, which is the answer, with
        its hop (a payment's is a receipt that says it did not move, as one the policy engine refused is). Direct there is no gateway to refuse it: the app says that
        the person is not signed in."""
        if command.kind == commands.MONEY:
            found = self.answers.payment(await money.send(self.clients.gateway, self.settings.mcp_url, None, money.parse(command.transfer), None, gateway=True))
            return JSONResponse({**found, "who": self.who(self.current(request))})
        if command.direct:
            raise NotSignedIn(f"{persona.first} is not signed in.", persona)
        await self.chat.without_token(command.message)          # raises the refusal, with its hop (`upstream_failed` says it)

    # -- developers and teams ---------------------------------------------------------------------------------
    async def dev_llm(self, request: Request) -> JSONResponse:
        body = await self.body(request)
        faq = 0 if body.get("faq") is True else body.get("faq")
        if isinstance(faq, int) and not isinstance(faq, bool):
            content = FAQS[faq % len(FAQS)]
        else:
            content = self.text(body, "message")
        asked = content
        variation = body.get("variation")
        if isinstance(variation, int) and not isinstance(variation, bool):
            content += f"\n\nRequest {variation}."      # a digit: the semantic cache never answers it, the model does
        result = await llm.ask(self.clients.gateway, self.settings.llm_url, self.settings.dev_llm_api_key, content,
                               DEVELOPER_MAX_TOKENS)
        log.info("developer call %d in %d ms", result["status"], result["ms"])
        return JSONResponse({**self.answers.call(result, hops.developer(result)), "question": asked})

    async def teams_list(self, request: Request) -> JSONResponse:
        return JSONResponse({"teams": [{"id": team, "name": name} for team, name in TEAMS],
                             "spend": await self.teams.spend_link()})

    async def teams_chat(self, request: Request) -> JSONResponse:
        body = await self.body(request)
        team, kind = body.get("team"), body.get("kind")
        if team not in dict(TEAMS) or kind not in PROMPTS:
            raise BadRequest("Pick a team and a kind of answer")
        result = await self.teams.chat(team, kind)
        log.info("team call %s %s %d in %d ms", team, kind, result["status"], result["ms"])
        # a run of several answers asks for one Spend over the whole of it: the page says when the run began
        began, now = moment(body.get("since")), time.time() * 1000
        since = None if began is None else int(min(max(began, now - SPAN // 2), now))
        return JSONResponse(self.answers.call(result, hops.workspace(result, dict(TEAMS)[team]), since=since))

    # -- evidence ---------------------------------------------------------------------------------------------------
    async def workspace_id(self) -> str | None:
        """The id of the AI workspace as the platform has it now (a re-seed makes it again with another), None where the platform does not say."""
        try:
            return (await self.keys.current_workspace()).get("id")
        except UpstreamError:
            return (self.keys.workspace or {}).get("id")

    async def find(self, request: Request) -> HTMLResponse | JSONResponse:
        """The exact item of a call in Gamma (its log entry, its trace, its decision, what a run spent), looked for now: a button of the evidence links here, the
        item is there some seconds after the call. With `resolve=1` it looks once and says `{state, url?}` (found, pending, missing, down), which is what
        the page asks again by itself while it is pending, and posts to the Lab UI (whose frame does not follow the redirect of another app). Followed as
        a link (a tab the browser opened) it answers at once with the small page that does the same looking and goes to the item: no connection is held."""
        try:
            item = parse_item(request.query_params, self.evidence.clock())
        except BadItem as e:
            raise BadRequest(str(e)) from e
        if request.query_params.get("resolve") == "1":
            found = await self.evidence.look(item)
            return JSONResponse({"state": found.state, **({"url": found.url} if found.state in (FOUND, MISSING) else {})})
        return HTMLResponse((self.static / "follow.html").read_text(encoding="utf-8"))

    # -- presenter --------------------------------------------------------------------------------------------------
    async def presenter_check(self, request: Request) -> JSONResponse:
        return JSONResponse(await self.presenter.check())

    async def presenter_warm_up(self, request: Request) -> JSONResponse:
        return JSONResponse(await self.presenter.warm_up(self.current(request)))

    async def presenter_reset(self, request: Request) -> JSONResponse:
        return JSONResponse(await self.presenter.reset())

    async def presenter_traffic(self, request: Request) -> JSONResponse:
        action = None
        if request.method == "POST":
            action = (await self.body(request)).get("action")
            if action not in PRESENTER_ACTIONS:
                raise BadRequest("action is pause or resume")
        return JSONResponse(await self.presenter.traffic(action))


def error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def upstream_failed(request: Request, e: UpstreamError) -> JSONResponse:
    log.warning("%s %s: %s%s", request.method, request.url.path, e.message, f" ({e.detail})" if e.detail else "")
    web = request.app.state.web
    return JSONResponse({"error": e.message, **({"rows": [web.answers.hop(row) for row in e.rows]} if e.rows else {}), **who_says(request)}, status_code=e.status)


def who_says(request: Request) -> dict:
    """What a failure adds: who asks now and who is signed in, as the call left them (a refused token is gone, and the page follows what the server holds, never what
    it guessed)."""
    web = request.app.state.web
    return {"who": web.who(web.current(request))}


async def bad_request(request: Request, e: BadRequest) -> JSONResponse:
    return error(str(e), 400)


async def not_signed_in(request: Request, e: NotSignedIn) -> JSONResponse:
    return JSONResponse({"error": str(e), **who_says(request)}, status_code=401)


async def http_error(request: Request, e: HTTPException) -> JSONResponse:
    """An unknown path or method is a JSON error like the others, not the framework's text."""
    return error(e.detail, e.status_code)


def build_app(settings: Settings, clients: Clients | None = None, static_dir: Path | None = None) -> Starlette:
    clients = clients or Clients.live()
    web = Web(settings, clients)
    web.static = static_dir or web.static

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        warm = [asyncio.create_task(web.keys.warm())]
        yield
        for task in warm:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await clients.aclose()

    app = Starlette(
        routes=[
            Route("/health", web.health, methods=["GET"]),
            Route("/login", web.login, methods=["GET"]),
            Route("/callback", web.callback, methods=["GET"]),
            Route("/api/config", web.config, methods=["GET"]),
            Route("/api/personas", web.personas, methods=["GET"]),
            Route("/api/commands", web.commands, methods=["GET"]),
            Route("/api/commands/{command}/run", web.run_command, methods=["POST"]),
            Route("/api/evidence", web.find, methods=["GET"]),
            Route("/api/session", web.session, methods=["GET"]),
            Route("/api/session", web.choose, methods=["POST"]),
            Route("/api/session", web.sign_out, methods=["DELETE"]),
            Route("/api/tokens", web.tokens, methods=["GET"]),
            Route("/api/token", web.token, methods=["POST"]),
            Route("/api/chat", web.ask_ace, methods=["POST"]),
            Route("/api/send-money", web.send_money, methods=["POST"]),
            Route("/api/dev/llm", web.dev_llm, methods=["POST"]),
            Route("/api/teams", web.teams_list, methods=["GET"]),
            Route("/api/teams/chat", web.teams_chat, methods=["POST"]),
            Route("/api/presenter/check", web.presenter_check, methods=["GET"]),
            Route("/api/presenter/warmup", web.presenter_warm_up, methods=["POST"]),
            Route("/api/presenter/reset", web.presenter_reset, methods=["POST"]),
            Route("/api/presenter/traffic", web.presenter_traffic, methods=["GET", "POST"]),
            Mount("/", StaticFiles(directory=web.static, html=True)),
        ],
        exception_handlers={UpstreamError: upstream_failed, BadRequest: bad_request, NotSignedIn: not_signed_in,
                            HTTPException: http_error},
        middleware=[Middleware(Guard, allowed_hosts=settings.allowed_hosts)],
        lifespan=lifespan,
    )
    app.state.web = web
    return app


class RedactedAccessLog(logging.Filter):
    """The server's access log names every request with its query. The one that brings the browser back from Access Management carries a code and a state: its
    line says the route and nothing else."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and args[2].startswith("/callback"):
            record.args = (*args[:2], "/callback", *args[3:])
        return True


def quiet_libraries() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)       # one line for each call to the platform would bury the lines that matter
    logging.getLogger("uvicorn.access").addFilter(RedactedAccessLog())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    quiet_libraries()
    try:
        settings = Settings.from_env()
    except ConfigError as e:
        raise SystemExit(f"bank-web: {e}") from e
    uvicorn.run(build_app(settings), host="0.0.0.0", port=settings.http_port, log_level="info")


if __name__ == "__main__":
    main()

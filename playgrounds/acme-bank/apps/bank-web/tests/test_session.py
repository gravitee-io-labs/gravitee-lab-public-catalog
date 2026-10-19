"""Signing in at Access Management's own login page (the authorization code flow with PKCE, in a popup), the cookie, the server-side session that holds the
tokens of each person who signed in, and what keeps other pages and other host names out."""

import base64
import dataclasses
import hashlib
import time
from pathlib import Path
import unittest
import unittest.mock
from urllib.parse import parse_qs, urlsplit

import httpx

import security
import sign_in
from people import PERSONAS
from sessions import Sessions
from tests.base import AppCase
from server import build_app
from tests.fakes import CLIENT, bearer_claims


class Flow(AppCase):
    """The sign-in as the browser does it, one step at a time, so that each step can be told wrong."""

    async def start(self, persona: str = "alice", client: httpx.AsyncClient | None = None) -> httpx.Response:
        return await self.go(f"/login?persona={persona}", client, **{"Sec-Fetch-Site": "same-origin"})

    async def login_page(self, started: httpx.Response) -> str:
        """The address the browser is sent back to, by the login page (the fake signs the person in on it, or refuses)."""
        async with httpx.AsyncClient(transport=self.world.transport) as am:
            page = await am.get(started.headers["location"])
        self.assertEqual(page.status_code, 302, page.text)
        return page.headers["location"]

    async def back(self, address: str, client: httpx.AsyncClient | None = None) -> httpx.Response:
        parts = urlsplit(address)
        return await self.go(f"{parts.path}?{parts.query}", client, **{"Sec-Fetch-Site": "same-site"})

    @staticmethod
    def outcome(response: httpx.Response) -> str:
        return parse_qs(urlsplit(response.headers["location"]).query)["outcome"][0]

    def held(self) -> list[str]:
        """The people whose tokens the server holds, by session."""
        return [person for session in self.web.sessions._items.values() for person in session.signed]


class TheLoginPage(Flow):
    async def test_the_browser_is_sent_to_access_managements_login_page_for_the_code_flow_with_pkce_and_the_hint_of_the_person(self):
        started = await self.start("bob")
        self.assertEqual(started.status_code, 302)
        parts = urlsplit(started.headers["location"])
        self.assertEqual(f"{parts.scheme}://{parts.netloc}{parts.path}", "http://am.test/acme-bank/oauth/authorize")
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.assertEqual(set(query), {"response_type", "client_id", "redirect_uri", "scope", "state", "code_challenge", "code_challenge_method", "login_hint", "prompt"})
        self.assertEqual((query["response_type"], query["client_id"], query["scope"]), ("code", "acme-bank-web", "openid profile email"))
        self.assertEqual((query["code_challenge_method"], query["login_hint"], query["prompt"]), ("S256", "bob@acme-bank.test", "login"))
        self.assertEqual(query["redirect_uri"], "http://localhost/callback")
        pending = self.web.signins._items[query["state"]]
        sent = base64.urlsafe_b64encode(hashlib.sha256(pending.verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(query["code_challenge"], sent, "S256 of the verifier the server keeps")
        self.assertNotIn(pending.verifier, started.headers["location"])
        self.assertNotIn(CLIENT[1], started.headers["location"], "the client secret never goes through the browser")
        self.assertEqual(started.headers["cache-control"], "no-store")

    async def test_the_address_the_browser_comes_back_to_is_the_one_it_came_from(self):
        """The page can be opened by `localhost` or by `127.0.0.1`: the cookie of one is not the other's, so the sign-in comes back to where it started."""
        for host in ("localhost:8110", "127.0.0.1:8110", "[::1]:8110"):
            started = await self.go("/login?persona=alice", **{"Host": host, "Sec-Fetch-Site": "same-origin"})
            self.assertEqual(parse_qs(urlsplit(started.headers["location"]).query)["redirect_uri"], [f"http://{host}/callback"], host)

    async def test_only_the_three_people_can_be_asked_for_and_nothing_a_link_says_is_where_the_browser_goes(self):
        for query in ("", "?persona=", "?persona=mallory", "?persona=http://evil.example/", "?persona=ALICE", "?next=http://evil.example/"):
            response = await self.go(f"/login{query}", **{"Sec-Fetch-Site": "same-origin"})
            self.assertEqual((response.status_code, response.json()["error"]), (400, "Unknown user"), query)
            self.assertNotIn("location", response.headers, query)
        self.assertEqual(self.web.signins._items, {})
        started = await self.go("/login?persona=tina&redirect_uri=http://evil.example/cb&client_id=other", **{"Sec-Fetch-Site": "same-origin"})
        query = parse_qs(urlsplit(started.headers["location"]).query)
        self.assertEqual((query["redirect_uri"], query["client_id"]), (["http://localhost/callback"], ["acme-bank-web"]))

    async def test_only_this_page_starts_a_sign_in_not_a_link_of_another_site(self):
        for site in ("cross-site", "same-site"):
            response = await self.go("/login?persona=alice", **{"Sec-Fetch-Site": site})
            self.assertEqual(response.status_code, 403, site)
        for site in ("same-origin", "none"):
            self.assertEqual((await self.go("/login?persona=alice", **{"Sec-Fetch-Site": site})).status_code, 302, site)
        self.assertEqual((await self.go("/login?persona=alice", **{"Sec-Fetch-Site": "cross-site", "Origin": "http://evil.example"})).status_code, 403)
        self.assertEqual(self.world.am.log, [])

    async def test_the_session_cookie_is_httponly_lax_and_holds_no_token_and_it_is_the_one_the_sign_in_is_bound_to(self):
        started = await self.start()
        cookie = started.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=lax", cookie, "a sign-in comes back from Access Management with a navigation of another site: Strict would drop the cookie")
        self.assertNotIn(".", cookie.split(";")[0])  # an opaque id, not a JWT
        pending = next(iter(self.web.signins._items.values()))
        self.assertEqual(pending.sid, self.http.cookies["acme_sid"])
        again = await self.start()                    # a second click, in the same browser: the same session
        self.assertEqual({p.sid for p in self.web.signins._items.values()}, {pending.sid})
        self.assertEqual(again.status_code, 302)


class Finishing(Flow):
    async def test_the_code_is_exchanged_by_the_server_with_the_verifier_the_secret_and_the_same_redirect_uri_and_the_person_is_signed_in(self):
        started = await self.start("alice")
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
        verifier = self.web.signins._items[state].verifier
        done = await self.back(await self.login_page(started))
        self.assertEqual((done.status_code, done.headers["location"]), (303, "/sign-in-done.html?outcome=signed-in"))
        (exchange,) = self.world.am.log
        self.assertEqual(exchange["authorization"], CLIENT)
        self.assertEqual({k: v for k, v in exchange["form"].items() if k != "code"},
                         {"grant_type": "authorization_code", "code_verifier": verifier, "redirect_uri": "http://localhost/callback"})
        self.assertEqual((await self.http.get("/api/session")).json(), {"persona": "alice", "name": "Alice Martin", "role": "customer", "signed": ["alice"]})

    async def test_nothing_of_the_sign_in_is_in_the_address_the_window_ends_on_nor_in_the_page_nor_in_a_log_of_the_app(self):
        with self.assertLogs("bank-web", level="DEBUG") as logs:
            started = await self.start("alice")
            state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
            verifier = self.web.signins._items[state].verifier
            address = await self.login_page(started)
            code = parse_qs(urlsplit(address).query)["code"][0]
            done = await self.back(address)
            token = (await self.http.post("/api/token")).json()["access_token"]
        shown = done.headers["location"] + done.text + (await self.http.get(done.headers["location"])).text
        for secret in (code, state, verifier, token, CLIENT[1]):
            self.assertNotIn(secret, shown)
            self.assertNotIn(secret, "\n".join(logs.output))
        self.assertEqual(logs.output, ["INFO:bank-web:sign-in alice"])

    def test_the_access_log_of_the_server_does_not_keep_the_code_and_the_state_that_come_back_in_an_address(self):
        """uvicorn logs the request line of every request, query included: the one that comes back from Access Management carries a code and a state."""
        import logging
        import server

        record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                                   ("127.0.0.1:5000", "GET", "/callback?code=abc123&state=xyz789", "1.1", 303), None)
        self.assertTrue(server.RedactedAccessLog().filter(record))
        self.assertEqual(record.getMessage(), '127.0.0.1:5000 - "GET /callback HTTP/1.1" 303')
        other = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", "/api/commands", "1.1", 200), None)
        server.RedactedAccessLog().filter(other)
        self.assertEqual(other.getMessage(), '127.0.0.1:5000 - "GET /api/commands HTTP/1.1" 200')

    async def test_a_state_that_comes_back_twice_is_taken_once(self):
        address = await self.login_page(await self.start("alice"))
        self.assertEqual(self.outcome(await self.back(address)), "signed-in")
        await self.http.delete("/api/session")
        await self.start("alice")                    # the same browser is on its way again; the first state is not the one that comes back
        self.assertEqual(self.outcome(await self.back(address)), "expired")
        self.assertEqual(len(self.world.am.log), 1, "the replay was refused before anything was asked of Access Management")
        self.assertEqual(self.held(), [])

    async def test_a_state_nobody_started_is_refused_and_so_is_a_return_with_none(self):
        for query in ("code=code-1&state=made-up", "code=code-1", "state=", "", "code=code-1&state=" + "x" * 5000):
            await self.start("alice")
            self.assertEqual(self.outcome(await self.go(f"/callback?{query}", **{"Sec-Fetch-Site": "same-site"})), "expired", query[:40])
        self.assertEqual((self.world.am.log, self.held()), ([], []))

    async def test_a_return_with_the_right_state_and_no_code_or_a_code_too_long_to_be_one_is_refused_without_asking_access_management(self):
        for query in ("", "&code=", "&code=" + "c" * 3000):
            started = await self.start("alice")
            state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
            self.assertEqual(self.outcome(await self.go(f"/callback?state={state}{query}", **{"Sec-Fetch-Site": "same-site"})), "refused", query[:20])
        self.assertEqual((self.world.am.log, self.held()), ([], []))

    async def test_a_sign_in_belongs_to_the_browser_that_started_it(self):
        """Somebody who is sent a link that carries a code and a state (a login CSRF) is not signed in as the person who made it, whether they have a session of
        their own or none. (Each is a sign-in of its own: a state is burned by the first return, whoever it was.)"""
        stranger = self.browser()
        self.addAsyncCleanup(stranger.aclose)
        for client in (stranger, await self.second_session()):
            address = await self.login_page(await self.start("alice"))
            self.assertEqual(self.outcome(await self.back(address, client)), "expired")
        self.assertEqual((self.world.am.log, self.held()), ([], []))

    async def second_session(self) -> httpx.AsyncClient:
        """A browser that has a session of its own."""
        other = self.browser()
        self.addAsyncCleanup(other.aclose)
        self.assertEqual((await self.start("bob", other)).status_code, 302)
        return other

    async def test_a_return_that_carries_no_session_cookie_is_refused(self):
        address = await self.login_page(await self.start("alice"))
        self.http.cookies.clear()
        self.assertEqual(self.outcome(await self.back(address)), "expired")
        self.assertEqual(self.world.am.log, [])

    async def test_a_sign_in_that_took_more_than_ten_minutes_is_refused(self):
        now = [1000.0]
        self.web.signins.clock = lambda: now[0]
        address = await self.login_page(await self.start("alice"))
        now[0] += sign_in.TTL + 1
        self.assertEqual(self.outcome(await self.back(address)), "expired")
        self.assertEqual(self.world.am.log, [])

    async def test_a_verifier_that_is_not_the_one_whose_challenge_was_sent_is_refused_by_access_management(self):
        started = await self.start("alice")
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
        self.web.signins._items[state] = dataclasses.replace(self.web.signins._items[state], verifier="x" * 43)
        self.assertEqual(self.outcome(await self.back(await self.login_page(started))), "failed")
        self.assertEqual(self.held(), [])

    async def test_a_code_is_used_once(self):
        address = await self.login_page(await self.start("alice"))
        code = parse_qs(urlsplit(address).query)["code"][0]
        self.assertEqual(self.outcome(await self.back(address)), "signed-in")
        again = await self.start("alice")                           # a state of its own, with the old code: Access Management does not accept it twice
        state = parse_qs(urlsplit(again.headers["location"]).query)["state"][0]
        self.assertEqual(self.outcome(await self.go(f"/callback?code={code}&state={state}", **{"Sec-Fetch-Site": "same-site"})), "failed")

    async def test_access_management_that_sends_the_person_back_with_an_error_is_a_refusal_and_nothing_is_asked_of_it(self):
        self.world.am.refuses_login = True
        self.assertEqual(self.outcome(await self.back(await self.login_page(await self.start("alice")))), "refused")
        self.assertEqual((self.world.am.log, self.held()), ([], []))

    async def test_a_person_who_is_not_one_of_the_three_is_not_signed_in_whatever_the_login_page_said(self):
        self.world.am.signs_in_as = "mallory@example.test"                      # a user of the domain, with a good token, who is nobody the app knows
        done = await self.back(await self.login_page(await self.start("alice")))
        self.assertEqual(self.outcome(done), "stranger")
        self.assertEqual((await self.http.get("/api/session")).json(), {"persona": None, "signed": []})
        self.assertEqual(self.held(), [])

    async def test_one_of_the_three_who_is_not_the_one_that_was_asked_for_is_not_signed_in_either(self):
        self.world.am.signs_in_as = "bob@acme-bank.test"                        # the hint was Alice's; the person who typed their password is Bob
        self.assertEqual(self.outcome(await self.back(await self.login_page(await self.start("alice")))), "other")
        self.assertEqual((await self.http.get("/api/session")).json(), {"persona": None, "signed": []})
        self.assertEqual(self.held(), [])

    async def test_access_management_that_does_not_answer_the_exchange_is_a_failure_and_says_so_in_the_log(self):
        address = await self.login_page(await self.start("alice"))
        self.world.am.down = True
        with self.assertLogs("bank-web", level="WARNING") as logs:
            self.assertEqual(self.outcome(await self.back(address)), "failed")
        self.assertIn("Access Management refused the sign-in (HTTP 503)", "\n".join(logs.output))
        self.assertEqual(self.held(), [])

    async def test_every_outcome_is_one_the_page_has_a_sentence_for(self):
        """The window's small page says how it ended with the words of `OUTCOMES`; the server never sends another."""
        import server

        sentences = (Path(__file__).resolve().parent.parent / "static" / "js" / "words.js").read_text()
        for outcome in server.OUTCOMES:
            self.assertIn(f"'{outcome}':" if "-" in outcome else f"{outcome}:", sentences, outcome)


class Choosing(Flow):
    async def test_the_personas_are_listed_with_the_accounts_they_may_send_from_the_login_that_is_shown_and_no_ready_made_question(self):
        people = (await self.http.get("/api/personas")).json()
        self.assertEqual([p["id"] for p in people], ["alice", "bob", "tina"])
        alice = people[0]
        self.assertEqual((alice["name"], alice["role"]), ("Alice Martin", "customer"))
        self.assertNotIn("examples", alice, "the ready-made questions are the commands': one place")
        self.assertEqual(alice["send"], {"from": "ACC-1001", "to": "ACC-2001", "amount": 600})
        self.assertEqual((alice["customer_id"], alice["accounts"]), ("C-1001", ["ACC-1001", "ACC-1002"]))
        self.assertEqual((people[2]["customer_id"], people[2]["accounts"]), (None, []))
        self.assertEqual([(p["username"], p["password"]) for p in people], [(f"{p}@acme-bank.test", "demo-password") for p in ("alice", "bob", "tina")],
                         "the demo user name and password of each: the login page asks for the password")

    async def test_the_answers_that_hold_the_demo_logins_hold_nothing_else_secret_and_no_answer_holds_the_secret_of_the_client(self):
        """/api/personas is the one route that gives a password, the demo one the login page asks for: its keys are these and the secret of the web client is in none."""
        people = (await self.http.get("/api/personas")).json()
        for person in people:
            self.assertEqual(set(person), {"id", "name", "role", "customer_id", "accounts", "send", "username", "password"})
        await self.sign_in("alice")
        for path in ("/api/personas", "/api/session", "/api/commands", "/api/config", "/api/tokens", "/api/teams", "/api/presenter/check"):
            self.assertNotIn(CLIENT[1], (await self.http.get(path)).text, path)
        self.assertNotIn(CLIENT[1], (await self.http.post("/api/token")).text)

    async def test_who_is_signed_in_and_who_asks(self):
        self.assertEqual((await self.http.get("/api/session")).json(), {"persona": None, "signed": []})
        await self.sign_in("bob")
        self.assertEqual((await self.http.get("/api/session")).json(), {"persona": "bob", "name": "Bob Chen", "role": "customer", "signed": ["bob"]})
        await self.sign_in("tina")
        self.assertEqual((await self.http.get("/api/session")).json()["persona"], "tina")           # the person who just signed in is the one who asks
        self.assertEqual((await self.http.get("/api/session")).json()["signed"], ["bob", "tina"])

    async def test_a_person_who_is_signed_in_is_chosen_with_no_login_page_and_one_who_is_not_has_to_sign_in(self):
        await self.sign_in("alice")
        await self.sign_in("bob")
        logins = len(self.world.am.logins)
        chosen = await self.http.post("/api/session", json={"persona": "alice"})
        self.assertEqual((chosen.status_code, chosen.json()["persona"], chosen.json()["signed"]), (200, "alice", ["alice", "bob"]))
        self.assertEqual((len(self.world.am.logins), len(self.world.am.log)), (logins, 2), "instant: Access Management was not asked")
        refused = await self.http.post("/api/session", json={"persona": "tina"})
        self.assertEqual((refused.status_code, refused.json()["error"]), (401, "Tina is not signed in."))
        self.assertEqual(refused.json()["who"]["persona"], "alice", "the page is told who still asks")
        self.assertEqual((await self.http.get("/api/session")).json()["persona"], "alice")

    async def test_choosing_somebody_who_is_not_one_of_the_three_or_with_no_session_is_refused(self):
        self.assertEqual((await self.http.post("/api/session", json={"persona": "alice"})).status_code, 401)
        for body in ({"persona": "mallory"}, {}, {"persona": ""}, {"persona": ["alice"]}, {"persona": None}):
            response = await self.http.post("/api/session", json=body)
            self.assertEqual(response.status_code, 400, body)

    async def test_nothing_is_answered_without_a_person_who_asks(self):
        for method, path in (("post", "/api/chat"), ("post", "/api/send-money"), ("get", "/api/tokens"), ("post", "/api/token")):
            response = await getattr(self.http, method)(path, **({"json": {}} if method == "post" else {}))
            self.assertEqual(response.status_code, 401, path)
        self.http.cookies.set("acme_sid", "made-up", domain="localhost")
        self.assertEqual((await self.http.get("/api/tokens")).status_code, 401)
        await self.start("alice")                      # a session that exists, with nobody in it
        self.assertEqual((await self.http.get("/api/tokens")).status_code, 401)

    async def test_signing_out_forgets_every_token_and_the_cookie(self):
        await self.sign_in("alice")
        await self.sign_in("tina")
        self.assertEqual(sorted(self.held()), ["alice", "tina"])
        response = await self.http.delete("/api/session")
        self.assertEqual(response.json(), {"persona": None, "signed": []})
        self.assertIn("acme_sid=", response.headers["set-cookie"])
        self.assertEqual(self.held(), [])
        self.assertEqual((await self.http.get("/api/session")).json(), {"persona": None, "signed": []})
        self.assertEqual((await self.http.post("/api/session", json={"persona": "alice"})).status_code, 401)

    async def test_signing_in_again_in_a_browser_that_has_a_session_keeps_the_session_and_adds_the_person(self):
        await self.sign_in("alice")
        first = self.http.cookies["acme_sid"]
        await self.sign_in("bob")
        self.assertEqual(self.http.cookies["acme_sid"], first)
        self.assertEqual(self.held(), ["alice", "bob"])
        other = self.browser()
        other.cookies = httpx.Cookies(self.http.cookies)                        # another tab of the same browser: one cookie jar
        self.assertEqual((await other.get("/api/session")).json()["signed"], ["alice", "bob"])
        await other.aclose()

    async def test_each_person_asks_with_their_own_token_and_in_a_conversation_of_their_own(self):
        await self.sign_in("alice")
        self.world.ace.reply = ("ok", [], {"sub": "id-alice", "act": {"sub": "ace-agent"}})
        await self.chat("one")
        await self.sign_in("bob")
        tokens = (await self.http.get("/api/tokens")).json()
        self.assertEqual(tokens["user"]["username"], "bob@acme-bank.test")
        self.assertIsNone(tokens["delegated"])  # the token Ace got for Alice is not Bob's to see
        token = (await self.http.post("/api/token")).json()["access_token"]
        self.assertEqual(bearer_claims(f"Bearer {token}")["username"], "bob@acme-bank.test")
        self.world.ace.reply = None
        await self.chat("two")
        await self.http.post("/api/session", json={"persona": "alice"})           # back to Alice, instantly: her own token, and a new conversation
        await self.chat("three")
        alice, bob, alice_again = self.world.ace.log
        self.assertEqual(bearer_claims(bob["authorization"])["username"], "bob@acme-bank.test")
        self.assertEqual(bearer_claims(alice_again["authorization"])["username"], "alice@acme-bank.test")
        self.assertEqual(bearer_claims(alice_again["authorization"])["n"], bearer_claims(alice["authorization"])["n"], "Alice's token was kept, not asked for again")
        self.assertEqual(len({alice["context_id"], bob["context_id"], alice_again["context_id"]}), 3)

    async def test_a_command_that_fails_in_the_app_leaves_the_session_as_it_was(self):
        await self.sign_in("alice")
        with unittest.mock.patch.object(type(self.web), "turn", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                await self.http.post("/api/commands/ask-ace-accounts/run", json={})
        self.assertEqual(self.held(), ["alice"])

    async def test_the_user_token_has_a_route_of_its_own_and_is_never_with_the_claims(self):
        await self.sign_in("alice")
        answer = await self.http.post("/api/token")
        token = answer.json()["access_token"]
        claims = (await self.http.get("/api/tokens")).json()
        self.assertEqual(token.count("."), 2)
        self.assertEqual(answer.headers["cache-control"], "no-store")
        self.assertEqual(claims["user"]["username"], "alice@acme-bank.test")
        self.assertNotIn(token, (await self.http.get("/api/tokens")).text)
        self.assertIsNone(claims["delegated"])


class TokenLifetime(Flow):
    async def test_a_token_about_to_expire_is_renewed_with_the_refresh_token(self):
        await self.sign_in("alice")
        next(iter(self.web.sessions._items.values())).signed["alice"].expires_at = time.time() + 5
        await self.chat()
        self.assertEqual([g["form"]["grant_type"] for g in self.world.am.log], ["authorization_code", "refresh_token"])
        self.assertEqual(bearer_claims(self.world.ace.log[0]["authorization"])["n"], 2)  # the renewed token, not the first

    async def test_two_calls_that_find_the_token_expiring_renew_it_once(self):
        """The Presenter's checks call the gateway as the person at the same time: a refresh token that is used twice is one Access Management may refuse."""
        import asyncio

        await self.sign_in("alice")
        session = next(iter(self.web.sessions._items.values()))
        session.signed["alice"].expires_at = time.time() + 5
        self.world.am.delay = 0.02                                                  # the calls overlap: the first has not been answered when the others look
        tokens = await asyncio.gather(*(self.web.am.valid_token(session) for _ in range(5)))
        self.assertEqual(len(set(tokens)), 1)
        self.assertEqual([g["form"]["grant_type"] for g in self.world.am.log], ["authorization_code", "refresh_token"], "one refresh, not five")
        self.assertEqual(self.held(), ["alice"])

    async def test_a_refresh_token_access_management_forgets_ends_the_sign_in_and_nothing_signs_the_person_in_behind_their_back(self):
        await self.sign_in("alice")
        await self.sign_in("bob")
        next(iter(self.web.sessions._items.values())).signed["bob"].expires_at = time.time() - 1
        self.world.am._refresh.clear()
        response = await self.http.post("/api/chat", json={"message": "hi"})
        self.assertEqual((response.status_code, response.json()["error"]), (401, "Your sign-in as Bob has ended. Sign in again."))
        self.assertEqual(response.json()["who"], {"persona": None, "signed": ["alice"]})
        self.assertEqual([g["form"]["grant_type"] for g in self.world.am.log], ["authorization_code", "authorization_code", "refresh_token"], "no password, ever")
        self.assertEqual(self.world.ace.log, [])
        await self.sign_in("bob")                                            # the same login page, as the first time
        self.assertEqual((await self.chat())["who"]["persona"], "bob")

    async def test_an_access_management_that_does_not_answer_the_refresh_is_not_the_end_of_the_sign_in(self):
        await self.sign_in("alice")
        next(iter(self.web.sessions._items.values())).signed["alice"].expires_at = time.time() - 1
        self.world.am.down = True
        response = await self.http.post("/api/chat", json={"message": "hi"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.held(), ["alice"])
        self.world.am.down = False
        self.assertEqual((await self.chat())["who"]["persona"], "alice")


class Signs(Flow):
    """What the window of a sign-in is served with: a policy of its own, and the small page that tells the page that opened it."""

    async def test_the_pages_of_a_sign_in_are_framed_by_nobody_and_load_nothing_but_their_own_script_and_style(self):
        expected = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.assertEqual(security.SIGN_IN_POLICY, expected)
        done = await self.http.get("/sign-in-done.html")
        started = await self.start("alice")
        back = await self.back(await self.login_page(started))
        for response in (done, started, back):
            self.assertEqual(response.headers["content-security-policy"], expected)
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(done.status_code, 200)
        self.assertNotIn("frame-ancestors http", done.headers["content-security-policy"], "the Lab UI frames the app, not the window of a sign-in")

    async def test_the_small_page_has_no_inline_script_and_names_only_its_own_script(self):
        page = (await self.http.get("/sign-in-done.html")).text
        self.assertNotIn("<script>", page.replace('<script type="module" src="/js/sign-in-done.js"></script>', ""))
        self.assertIn('src="/js/sign-in-done.js"', page)
        self.assertNotIn("http://", page.replace("http://www.w3.org", ""))
        self.assertNotIn("onclick", page)

    async def test_the_pages_policy_is_not_changed_by_the_sign_in(self):
        self.assertIn("frame-ancestors http://localhost:9000", (await self.http.get("/")).headers["content-security-policy"])


class Guarding(AppCase):
    async def test_a_request_from_another_page_is_refused(self):
        for origin in ("http://evil.example", "null", "http://localhost:9999"):
            response = await self.http.post("/api/session", json={"persona": "alice"}, headers={"Origin": origin})
            self.assertEqual(response.status_code, 403, origin)
        self.assertEqual(self.world.am.log, [])

    async def test_a_browser_that_sends_no_origin_but_says_it_is_cross_site_is_refused(self):
        response = await self.http.post(
            "/api/session", json={"persona": "alice"}, headers={"Origin": "", "Sec-Fetch-Site": "cross-site"}
        )
        self.assertEqual(response.status_code, 403)

    async def test_a_tool_that_sends_neither_is_let_in(self):
        tool = self.browser()
        del tool.headers["Origin"]
        await self.sign_in("alice", tool)
        await tool.aclose()

    async def test_every_request_that_changes_something_is_checked(self):
        await self.sign_in("alice")
        foreign = {"Origin": "http://evil.example"}
        self.assertEqual((await self.http.delete("/api/session", headers=foreign)).status_code, 403)
        self.assertEqual((await self.http.post("/api/presenter/reset", headers=foreign)).status_code, 403)
        self.assertEqual(
            (await self.http.post("/api/presenter/traffic", json={"action": "pause"}, headers=foreign)).status_code, 403
        )
        self.assertEqual(self.world.bank.resets, 0)
        self.assertFalse(self.world.traffic.paused)

    def tool(self):
        """A client that sends neither an Origin nor Sec-Fetch-Site, as curl does."""
        client = self.browser()
        del client.headers["Origin"]
        self.addAsyncCleanup(client.aclose)
        return client

    async def test_a_host_the_app_is_not_meant_for_is_refused(self):
        tool = self.tool()
        for path in ("/api/personas", "/"):
            response = await tool.get(path, headers={"Host": "rebind.example"})
            self.assertEqual(response.status_code, 421, path)
        self.assertEqual((await tool.get("/health", headers={"Host": "bank-web:8000"})).status_code, 200)
        self.assertEqual((await tool.get("/api/personas", headers={"Host": "127.0.0.1:8110"})).status_code, 200)
        self.assertEqual((await tool.get("/api/personas", headers={"Host": "[::1]:8110"})).status_code, 200)

    async def test_the_allowed_hosts_are_a_setting(self):
        self.app = build_app(self.world.settings(allowed_hosts=("bank.example",)), self.world.clients())
        client = self.browser()
        del client.headers["Origin"]
        self.assertEqual((await client.get("/api/personas", headers={"Host": "bank.example"})).status_code, 200)
        self.assertEqual((await client.get("/api/personas")).status_code, 421)
        await client.aclose()

    async def test_a_page_elsewhere_cannot_make_the_app_do_the_work_of_a_get(self):
        """/api/evidence and /api/presenter/check call the platform: another web page can make a visitor's browser GET them, and the app must
        not answer. A GET of the app's own page, one typed in the address bar and a tool's are let in."""
        paths = ("/api/presenter/check", "/api/evidence?kind=logs&api=llm&request=req-12345678&at=1791000000000", "/api/teams",
                 "/api/presenter/traffic", "/api/personas", "/api/commands")
        for path in paths:
            for headers in ({"Origin": "http://evil.example"}, {"Origin": "", "Sec-Fetch-Site": "cross-site"},
                            {"Origin": "", "Sec-Fetch-Site": "same-site"}):
                response = await self.http.get(path, headers=headers)
                self.assertEqual(response.status_code, 403, f"{path} {headers}")
        self.assertEqual(self.world.apim.log, [])          # nothing was asked of the platform for them
        tool = self.tool()
        for path in paths[:2]:
            self.assertEqual((await tool.get(path)).status_code, 200, path)
            self.assertEqual((await tool.get(path, headers={"Sec-Fetch-Site": "same-origin"})).status_code, 200, path)
            self.assertEqual((await tool.get(path, headers={"Sec-Fetch-Site": "none"})).status_code, 200, path)
        self.assertEqual((await self.http.get("/api/personas")).status_code, 200)                  # the page's own call, with its Origin

    async def test_a_get_of_an_api_route_must_carry_the_header_only_the_page_adds_even_where_the_browser_sends_no_fetch_metadata(self):
        """A browser before Chrome 76 sends no Sec-Fetch-Site and lets any page make it GET: the header is what such a page cannot add."""
        bare = self.browser()
        del bare.headers["X-Requested-With"]
        self.addAsyncCleanup(bare.aclose)
        for path in ("/api/presenter/check", "/api/teams", "/api/presenter/traffic", "/api/personas", "/api/commands", "/api/config", "/api/session"):
            for headers in ({}, {"X-Requested-With": "something else"}, {"X-Requested-With": ""}):
                response = await bare.get(path, headers=headers)
                self.assertEqual(response.status_code, 403, f"{path} {headers}")
            self.assertEqual((await bare.get(path, headers={"X-Requested-With": "acme-bank"})).status_code, 200, path)
        # a link of a result opens /api/evidence, and a link cannot add a header: the Sec-Fetch rules are all it has. It answers its small page, which looks nothing up
        trace = "/api/evidence?kind=trace&api=llm&request=req-12345678&at=1791000000000"
        self.assertEqual((await bare.get(trace)).status_code, 200)
        self.assertEqual((await bare.get(trace, headers={"Origin": "", "Sec-Fetch-Site": "cross-site"})).status_code, 403)
        # what changes something is guarded by its Origin as before, and needs no header (nobody is signed in: the guard let it through, the route says 401)
        self.assertEqual((await bare.post("/api/session", json={"persona": "alice"})).status_code, 401)
        self.assertEqual((await bare.delete("/api/session")).status_code, 200)
        self.assertEqual((await bare.get("/health")).status_code, 200)

    async def test_a_head_of_an_api_route_is_asked_the_same_as_a_get_for_the_framework_runs_the_get_route_for_it(self):
        """HEAD /api/presenter/check makes about ten model calls: with no header a page elsewhere in a browser that sends no fetch metadata could
        make them."""
        bare = self.browser()
        del bare.headers["X-Requested-With"]
        self.addAsyncCleanup(bare.aclose)
        for path in ("/api/presenter/check", "/api/teams", "/api/commands"):
            self.assertEqual((await bare.head(path)).status_code, 403, path)
            self.assertEqual((await bare.head(path, headers={"X-Requested-With": "something else"})).status_code, 403, path)
            self.assertEqual((await bare.head(path, headers={"X-Requested-With": "acme-bank"})).status_code, 200, path)
        self.world.apim.log.clear()
        await bare.head("/api/teams")
        self.assertEqual(self.world.apim.log, [], "the refused request did none of the work")
        trace = "/api/evidence?kind=trace&api=llm&request=req-12345678&at=1791000000000"
        self.assertEqual((await bare.head(trace)).status_code, 200)                     # the one route a link opens

    async def test_the_pages_files_and_the_health_check_are_not_asked_where_they_come_from(self):
        for path in ("/", "/app.js", "/style.css", "/health"):
            response = await self.http.get(path, headers={"Origin": "http://evil.example", "Sec-Fetch-Site": "cross-site"})
            self.assertEqual(response.status_code, 200, path)

    async def test_the_content_security_policy_allows_nothing_but_the_page_itself(self):
        """The whole policy, so that taking a part of it out (default-src is what keeps a script from elsewhere out) fails here.
        Only the Lab UI, which shows the app next to the guide, may frame the page."""
        from security import POLICY

        expected = ("default-src 'self'; img-src 'self' data:; frame-ancestors http://localhost:9000 http://127.0.0.1:9000; "
                    "base-uri 'none'; form-action 'self'")
        self.assertEqual(POLICY, expected)
        for path in ("/", "/api/personas", "/app.js"):
            self.assertEqual((await self.http.get(path)).headers["content-security-policy"], expected, path)

    async def test_answers_carry_the_headers_that_keep_the_page_to_itself(self):
        api = await self.http.get("/api/personas")
        page = await self.http.get("/")
        for response in (api, page):
            self.assertIn("frame-ancestors http://localhost:9000 http://127.0.0.1:9000;", response.headers["content-security-policy"])
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(api.headers["cache-control"], "no-store")
        self.assertEqual(page.headers["cache-control"], "no-cache")

    async def test_the_page_is_served_from_the_same_origin_with_nothing_external(self):
        page = await self.http.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("<title>ACME Bank</title>", page.text)
        self.assertNotIn("http://", page.text.replace("http://www.w3.org", ""))  # no CDN, no external font or script
        self.assertNotIn("https://", page.text)
        for path, kind in (("/app.js", "javascript"), ("/style.css", "css")):
            asset = await self.http.get(path)
            self.assertEqual(asset.status_code, 200, path)
            self.assertIn(kind, asset.headers["content-type"])
            self.assertNotIn("https://", asset.text, path)

    async def test_the_page_never_turns_text_into_markup(self):
        script = (await self.http.get("/app.js")).text
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(forbidden, script)
        self.assertNotIn("style=", (await self.http.get("/")).text)  # the page's policy does not allow style attributes

    async def test_an_unknown_api_path_is_a_json_error(self):
        response = await self.http.get("/api/nothing")
        self.assertEqual((response.status_code, "error" in response.json()), (404, True))


class Store(unittest.TestCase):
    def test_a_session_ends_after_its_lifetime(self):
        now = [1000.0]
        sessions = Sessions(ttl=60, clock=lambda: now[0])
        sid, _ = sessions.open()
        self.assertIsNotNone(sessions.get(sid))
        now[0] += 61
        self.assertIsNone(sessions.get(sid))

    def test_the_oldest_session_goes_when_there_are_too_many(self):
        sessions = Sessions(limit=2)
        first, _ = sessions.open()
        sessions.open()
        third, _ = sessions.open()
        self.assertIsNone(sessions.get(first))
        self.assertIsNotNone(sessions.get(third))

    def test_a_flood_of_visits_signs_nobody_out_the_sessions_that_hold_no_token_go_first(self):
        from sessions import Tokens

        sessions = Sessions(limit=3)
        signed, session = sessions.open()
        session.sign_in(PERSONAS["alice"], Tokens("a", None, 0))
        for _ in range(50):
            sessions.open()
        self.assertIs(sessions.get(signed), session, "a person signed in stays however many come")
        self.assertEqual(len(sessions._items), 3)

    def test_where_every_session_holds_a_token_the_oldest_goes(self):
        from sessions import Tokens

        sessions = Sessions(limit=2)
        ids = []
        for person in ("alice", "bob", "tina"):
            sid, session = sessions.open()
            session.sign_in(PERSONAS[person], Tokens("t", None, 0))
            ids.append(sid)
        self.assertEqual([sessions.get(sid) is not None for sid in ids], [False, True, True])

    def test_a_person_forgotten_is_forgotten_with_what_was_theirs_and_somebody_else_keeps_theirs(self):
        from sessions import Tokens

        session = Sessions().open()[1]
        session.sign_in(PERSONAS["alice"], Tokens("a", None, 0))
        session.contexts["on"] = "ctx"
        session.sign_in(PERSONAS["bob"], Tokens("b", None, 0))
        self.assertEqual((session.persona.id, session.contexts, session.tokens.access_token), ("bob", {}, "b"))
        session.contexts["on"] = "ctx"
        session.forget(PERSONAS["alice"])
        self.assertEqual((session.persona.id, session.contexts, list(session.signed)), ("bob", {"on": "ctx"}, ["bob"]))
        session.forget(PERSONAS["bob"])
        self.assertEqual((session.persona, session.contexts, session.tokens), (None, {}, None))


class Pending(unittest.TestCase):
    """The sign-ins on their way."""

    def test_the_challenge_is_the_s256_of_the_verifier_as_rfc_7636_gives_it(self):
        self.assertEqual(sign_in.challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"), "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")

    def test_every_sign_in_has_a_state_and_a_verifier_of_its_own_and_the_verifier_is_never_given_out(self):
        signins = sign_in.SignIns()
        seen = [signins.begin(f"sid-{n}", "alice", "http://localhost/callback") for n in range(5)]
        self.assertEqual(len({state for state, _ in seen}), 5)
        self.assertTrue(all(len(state) >= 43 for state, _ in seen), "a state nobody can guess: 256 bits")
        self.assertEqual(len({p.verifier for p in signins._items.values()}), 5)
        for state, challenge in seen:
            pending = signins._items[state]
            self.assertTrue(43 <= len(pending.verifier) <= 128, "RFC 7636: 43 to 128 characters")
            self.assertRegex(pending.verifier, r"^[A-Za-z0-9_-]+$")
            self.assertEqual(challenge, sign_in.challenge(pending.verifier))
            self.assertNotIn(pending.verifier, (state, challenge))

    def test_a_state_is_taken_once_and_one_that_is_not_there_is_nothing(self):
        signins = sign_in.SignIns()
        state, _ = signins.begin("sid", "bob", "http://localhost/callback")
        taken = signins.take(state)
        self.assertEqual((taken.persona, taken.sid, taken.redirect_uri), ("bob", "sid", "http://localhost/callback"))
        self.assertIsNone(signins.take(state))
        self.assertIsNone(signins.take("never-made"))

    def test_a_sign_in_lives_ten_minutes_and_an_expired_one_is_burned_by_trying_it(self):
        now = [0.0]
        signins = sign_in.SignIns(clock=lambda: now[0])
        state, _ = signins.begin("sid", "alice", "u")
        now[0] = sign_in.TTL
        self.assertIsNotNone(signins.take(state), "up to the last second")
        state, _ = signins.begin("sid", "alice", "u")
        now[0] += sign_in.TTL + 1
        self.assertIsNone(signins.take(state))
        self.assertEqual(signins._items, {})

    def test_the_sign_ins_on_their_way_are_bounded_for_all_and_for_each_session(self):
        signins = sign_in.SignIns(limit=10, per_session=3)
        mine = [signins.begin("mine", "alice", "u")[0] for _ in range(6)]
        self.assertEqual([s for s in mine if s in signins._items], mine[-3:], "the oldest of a session goes when it starts another")
        for n in range(20):
            signins.begin(f"other-{n}", "bob", "u")
        self.assertEqual(len(signins._items), 10)
        self.assertNotIn(mine[-1], signins._items, "and the oldest of all goes when there are too many")
        self.assertIn(list(signins._items)[-1], signins._items)


if __name__ == "__main__":
    unittest.main()

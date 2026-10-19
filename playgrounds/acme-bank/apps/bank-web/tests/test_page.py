"""What the page promises, read from its files: no browser runs here. How it looks and behaves is checked in a browser over
`python -m tests.fake_stack` (see static/README.md); these keep the rules a browser would only show by failing."""

import re
from pathlib import Path

import answers
import hops
import security
from tests.base import AppCase

STATIC = Path(__file__).resolve().parent.parent / "static"


def scripts() -> dict[str, str]:
    """Every script the page loads, by its path under static/."""
    return {str(p.relative_to(STATIC)): p.read_text() for p in sorted(STATIC.rglob("*.js"))}


def function_of(script: str, name: str) -> str:
    """The source of one top-level function of a module: from its line to the closing brace at the margin."""
    found = re.search(rf"^(?:export )?(?:async )?function {name}\(.*?^}}$", script, re.DOTALL | re.MULTILINE)
    assert found, f"no function {name}"
    return found.group(0)


def hex_of(value: str) -> tuple[float, float, float, float]:
    """(r, g, b, alpha) of a #rrggbb or rgba(r, g, b, a) token, channels 0 to 255."""
    value = value.strip()
    if value.startswith("#"):
        return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16), 1.0
    r, g, b, *a = [float(part) for part in re.findall(r"[\d.]+", value)]
    return r, g, b, a[0] if a else 1.0


def luminance(r: float, g: float, b: float) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(front: tuple, back: tuple, under: tuple) -> float:
    """The contrast of a color on a background; a translucent background is laid over `under` first."""
    def over(top: tuple, bottom: tuple) -> tuple:
        a = top[3]
        return tuple(top[i] * a + bottom[i] * (1 - a) for i in range(3)) + (1.0,)

    background = over(back, under)
    text = over(front, background)
    hi, lo = sorted((luminance(*text[:3]), luminance(*background[:3])), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def tokens(css: str) -> dict[str, tuple[str, str]]:
    """The tokens of the stylesheet as (light, dark): `--name: light-dark(a, b)`; a plain value is the same in both."""
    found = {}
    for name, value in re.findall(r"(--[\w-]+):\s*([^;]+);", css.split("*, *::before")[0]):
        pair = re.match(r"light-dark\((.+)\)$", value.strip())
        if pair:
            parts = re.split(r",\s*(?![^(]*\))", pair.group(1))
            found[name] = (parts[0].strip(), parts[1].strip())
        elif re.match(r"(#[0-9a-fA-F]{6}|rgba?\()", value.strip()):
            found[name] = (value.strip(), value.strip())
    return found


def rules(css: str, media: str = "") -> list[tuple[str, str, str]]:
    """The rules of a stylesheet as (media condition, selector, body), @media blocks flattened: enough CSS for the tests below."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    found, i = [], 0
    while i < len(css):
        brace = css.find("{", i)
        if brace < 0:
            break
        head, depth, j = css[i:brace].strip(), 1, brace + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        body = css[brace + 1:j - 1]
        if head.startswith("@media"):
            found += rules(body, head.removeprefix("@media").strip())
        elif head.startswith("@container"):
            found += rules(body, head.removeprefix("@").strip())          # "container head (max-width: 720px)"
        elif not head.startswith("@"):
            found.append((media, " ".join(head.split()), body.strip()))
        i = j
    return found


def declared(css: str, selector: str, media: str = "") -> str:
    """The declarations of every rule whose selector list holds `selector` exactly (in the given media condition)."""
    return " ".join(body for m, sel, body in rules(css) if m == media and (selector == sel or selector in [part.strip() for part in sel.split(",")]))


class TokensDrawer(AppCase):
    async def test_the_token_is_in_a_read_only_field_beside_the_copy_button(self):
        page = (await self.http.get("/")).text
        field = re.search(r'<textarea[^>]*id="tokens-value"[^>]*>', page)
        self.assertIsNotNone(field)
        self.assertIn("readonly", field.group(0))
        self.assertIn('id="tokens-copy"', page)

    async def test_the_token_is_fetched_when_the_drawer_opens_and_emptied_when_it_closes(self):
        script = (await self.http.get("/js/tokens.js")).text
        self.assertIn("'/api/token'", function_of(script, "openTokens"))
        wiring = function_of(script, "initTokens")
        self.assertIn("addEventListener('close', () => { $('#tokens-value').value = ''; })", wiring)

    async def test_the_copy_is_made_inside_the_click_before_anything_is_awaited(self):
        copy = function_of((await self.http.get("/js/tokens.js")).text, "copyToken")
        self.assertNotIn("await", copy)  # a browser refuses a clipboard write that comes after an await
        self.assertNotIn("api(", copy)
        self.assertIn("navigator.clipboard.writeText(field.value)", copy)
        self.assertIn("field.select()", copy)  # where the write is refused the token stays selected for the keyboard


class Conversation(AppCase):
    async def test_another_user_or_a_sign_out_starts_a_new_conversation(self):
        script = (await self.http.get("/js/session.js")).text
        self.assertIn("state.conversation += 1", function_of(script, "adopt"))
        for name in ("switchTo", "signInAs", "signOut"):
            self.assertIn("bus.emit('conversation-reset'", function_of(script, name), name)
        self.assertIn("box().replaceChildren(emptyNode())", function_of((await self.http.get("/js/chat.js")).text, "resetConversation"))
        self.assertIn("forgetTurns('assistant')", function_of((await self.http.get("/js/chat.js")).text, "resetConversation"))      # nothing of it is kept, folded or not

    async def test_an_answer_that_comes_back_after_the_user_changed_is_dropped(self):
        chat, money = (await self.http.get("/js/chat.js")).text, (await self.http.get("/js/money.js")).text
        self.assertIn("if (epoch !== state.conversation) return null;", function_of(chat, "finish"))
        self.assertIn("if (epoch !== state.conversation) return null;", function_of(money, "run"))      # a payment of the form and of a command alike

    async def test_a_question_is_sent_once_whatever_the_clicks(self):
        chat = (await self.http.get("/js/chat.js")).text
        self.assertIn("state.busy", function_of(chat, "ask").split("\n", 3)[2])
        self.assertIn("if (state.busy) return null;", function_of(chat, "playChat"))
        self.assertIn("if (paying", function_of((await self.http.get("/js/money.js")).text, "submit"))
        self.assertIn("if (paying) return null;", function_of((await self.http.get("/js/money.js")).text, "playMoney"))

    async def test_a_wait_has_an_end_and_says_what_to_do(self):
        chat, errors = (await self.http.get("/js/chat.js")).text, (await self.http.get("/js/errors.js")).text
        self.assertIn("timeout: ASK_TIMEOUT", function_of(chat, "send"))
        self.assertIn("controller", function_of(chat, "send"))                       # the person can stop waiting
        self.assertIn("failure(response)", function_of(chat, "finish"))               # and a failure is told in plain English
        self.assertIn("Is Ollama running?", errors)                                  # with the operator's question folded away, not in the text
        self.assertNotIn("Ollama", function_of(errors, "failure").split("hint")[0].split("text:")[1])

    async def test_a_question_typed_and_a_command_are_asked_and_answered_by_the_same_code(self):
        chat = (await self.http.get("/js/chat.js")).text
        self.assertIn("return send({", function_of(chat, "ask"))
        self.assertIn("return send({", function_of(chat, "playChat"))
        self.assertIn("/api/commands/${command.id}/run", function_of(chat, "playChat"))
        self.assertIn("select: Boolean(command)", function_of(chat, "finish"))       # the answer to a command is selected


class OneThingAtATime(AppCase):
    """Anything that moves money, spends a budget or starts the bank over marks the page busy, and the commands wait for it."""

    async def test_a_payment_a_reset_and_a_conversation_mark_the_page_busy(self):
        money, bank, chat = (await self.http.get("/js/money.js")).text, (await self.http.get("/js/bank.js")).text, (await self.http.get("/js/chat.js")).text
        for name, script, function in (("a payment, of the form or of a command", money, "run"), ("the reset of the bank", bank, "startOver")):
            self.assertIn("begin()", function_of(script, function), name)
        self.assertIn("begin()", function_of(chat, "setBusy"))                      # and a conversation: Ace answering

    async def test_the_reset_of_the_bank_does_not_start_in_the_middle_of_a_run(self):
        commands = (await self.http.get("/js/commands.js")).text
        self.assertIn(".rail-foot .btn", function_of(commands, "paint"))                    # it waits like the commands: aria-disabled, written in place
        guarded = function_of(commands, "startBankOver")
        self.assertIn("if (isBusy()) return;", guarded)
        self.assertLess(guarded.index("if (isBusy()) return;"), guarded.index("startOver()"))

    async def test_a_command_is_not_a_disabled_button_so_that_the_focus_stays_where_the_person_put_it(self):
        commands = (await self.http.get("/js/commands.js")).text
        paint = function_of(commands, "paint")
        self.assertIn("button.setAttribute('aria-disabled', 'true')", paint)
        self.assertNotIn("disabled = ", commands)
        self.assertNotIn("'disabled'", commands)
        self.assertNotIn("disabled: isBusy()", commands)
        self.assertIn("for (const event of ['running', 'busy']) bus.on(event, paint);", function_of(commands, "initCommands"))      # a run does not draw the rail again: it keeps its scroll

    async def test_a_command_does_not_start_while_anything_runs_and_says_so(self):
        run = function_of((await self.http.get("/js/commands.js")).text, "runCommand")
        self.assertIn("ports.state.running || ports.isBusy()", run)
        self.assertIn("Something is still running. Run it when it is done.", run)


class Markup(AppCase):
    async def test_the_page_never_turns_text_into_markup(self):
        for path, script in scripts().items():
            for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
                self.assertNotIn(forbidden, script, path)
        self.assertNotIn("style=", (await self.http.get("/")).text)  # the page's policy does not allow style attributes
        for path, script in scripts().items():
            self.assertNotIn("setAttribute('style'", script, path)

    async def test_a_link_that_opens_gamma_opens_in_a_new_tab_without_giving_it_the_page(self):
        page = (await self.http.get("/")).text
        self.assertRegex(page, r'<a [^>]*id="gamma-link"[^>]*target="_blank"[^>]*rel="noopener"')
        for path, script in scripts().items():
            for call in re.findall(r"target: '_blank'[^}]*\}", script):
                self.assertIn("rel: 'noopener'", call, path)

    async def test_nothing_is_loaded_from_outside(self):
        for path in ["index.html", "style.css", *scripts()]:
            text = (STATIC / path).read_text()
            urls = re.findall(r"https?://[^\s'\")]+", text)
            lab = ["http://localhost:9000", "http://127.0.0.1:9000"] if path == "js/embed.js" else []      # where the Lab UI is: the targets of a message to its frame, never loaded
            self.assertEqual([u for u in urls if "www.w3.org" not in u], lab, path)
        self.assertNotIn("@import", (STATIC / "style.css").read_text())
        self.assertNotRegex((STATIC / "style.css").read_text(), r"url\((?!['\"]?#)")

    async def test_every_script_is_served_by_the_app(self):
        for path in scripts():
            response = await self.http.get(f"/{path}")
            self.assertEqual(response.status_code, 200, path)
            self.assertIn("javascript", response.headers["content-type"])


class TheLabUI(AppCase):
    """The page framed by the Lab UI: what it says to it, what it hears from it, and what it never does. It says where to go in Gamma and that it is ready, and
    it hears the guide's actions: it never says where the person is and never hears which page of the guide is read. A Back pressed in another frame must not
    undo anything the page did."""

    def embed(self) -> str:
        return (STATIC / "js" / "embed.js").read_text()

    def actions(self) -> str:
        return (STATIC / "js" / "actions.js").read_text()

    def test_the_page_says_two_things_to_the_lab_ui_and_hears_one(self):
        every = scripts()
        said = [(path, found) for path, script in every.items() for found in re.findall(r"type: '(gravitee-lab:[\w-]+)'", script)]
        self.assertEqual(said, [("js/actions.js", "gravitee-lab:ready"), ("js/embed.js", "gravitee-lab:open")])
        heard = [(path, found) for path, script in every.items() for found in re.findall(r"\.type !== '(gravitee-lab:[\w-]+)'", script)]
        self.assertEqual(heard, [("js/actions.js", "gravitee-lab:action")])
        for path, script in every.items():
            # the window of a sign-in is not the Lab UI: it is heard in sign-in.js, from its own window (see the test of the sign-in), and says one thing to its own opener
            listens = {"js/actions.js": 1, "js/sign-in.js": 1}.get(path, 0)
            self.assertEqual(len(re.findall(r"addEventListener\('message'", script)), listens, f"{path}: one listener for what the Lab UI says, and it is the actions'; one for the window of a sign-in")
            self.assertEqual(script.count("postMessage"), {"js/embed.js": 1, "js/sign-in-done.js": 1}.get(path, 0), f"{path}: one way to say something to the Lab UI, one to the opener of a sign-in")
        self.assertIn("parent.postMessage(message, origin)", function_of(self.embed(), "tell"))
        self.assertNotIn("event.source", self.embed())

    def test_the_window_of_a_sign_in_is_heard_only_from_the_window_the_page_opened_and_from_its_own_origin_and_it_speaks_only_to_its_own_origin(self):
        signin, done = (STATIC / "js" / "sign-in.js").read_text(), (STATIC / "js" / "sign-in-done.js").read_text()
        heard = signin[signin.index("const heard = (event) => {"):signin.index("/* A window that closes itself")]
        order = ["event.source !== popup", "event.origin !== ports.origin()", "message.type !== SIGN_IN_MESSAGE", "Object.hasOwn(SIGN_IN, message.outcome)"]
        self.assertEqual([heard.index(needle) for needle in order], sorted(heard.index(needle) for needle in order), "source, origin, type, then the outcome")
        self.assertIn("origin: () => location.origin", signin, "the page's own origin, not a list")
        self.assertNotIn("'*'", signin + done)
        self.assertIn("page.opener.postMessage({ type: SIGN_IN_MESSAGE, outcome }, page.origin);", done)
        self.assertIn("origin: location.origin, opener: window.opener", done, "its own origin, and what opened it")
        self.assertNotIn("window.parent", done, "a window of a sign-in is a window of its own: it has an opener, never a parent")
        self.assertIn("/login?persona=${encodeURIComponent(persona)}", signin)
        self.assertRegex(signin, r"window\.open\(url, NAME, FEATURES\)")
        code = re.sub(r"/\*.*?\*/", "", signin + done + (STATIC / "js" / "session.js").read_text(), flags=re.DOTALL)
        self.assertNotIn("password", code, "no password goes through the page's code of a sign-in: Access Management's page asks for it")
        self.assertNotIn("access_token", code)
        self.assertNotIn("code_verifier", "".join(scripts().values()), "the verifier never reaches the page")

    def test_a_command_signs_nobody_in_the_person_control_is_the_one_way_and_a_command_goes_on_with_the_token_it_finds_or_none(self):
        """Only session.js, for a click on a person, reaches the window of a sign-in. A command asks as a person who is signed in (`askAs`: a switch, no window) and goes
        on with the token it finds, or none."""
        every = scripts()
        for path, script in every.items():
            self.assertEqual("sign-in.js" in "".join(re.findall(r"from '\./([\w-]+\.js)'", script)), path == "js/session.js", f"{path}: only the person's choice imports the sign-in window")
        session = every["js/session.js"]
        self.assertIn("if (state.signed.includes(id)) await asPerson(id);", function_of(session, "askAs"), "a switch for somebody who is signed in, and nothing for somebody who is not")
        self.assertNotIn("signInAs", function_of(session, "askAs"))
        for name, script, function in (("chat.js", every["js/chat.js"], "playChat"), ("money.js", every["js/money.js"], "playMoney")):
            body = function_of(script, function)
            self.assertIn("await askAs(command.persona);", body, name)
            self.assertNotIn("return null;\n  if (!asks)", body, f"{name}: a command goes on whatever it finds")
        self.assertNotIn("persona ?", function_of(every["js/chat.js"], "playChat"), "the same rule for every command")

    def test_the_button_of_a_refused_answer_opens_the_menu_of_who_is_asking_and_leaves_it_open(self):
        """The menu closes for a click outside it, at the document: the click on the button of the answer, which opens the menu from inside its own event, would reach the
        document after it and close the menu again."""
        finish = function_of((STATIC / "js" / "chat.js").read_text(), "finish")
        self.assertIn("event.stopPropagation(); $('#person-button').click();", finish)
        self.assertIn("document.addEventListener('click', (event) => { if (!home.contains(event.target)) close(); });", (STATIC / "js" / "menus.js").read_text())

    def test_a_hop_of_the_pages_own_calls_nobody_in_the_words_of_the_servers_hops(self):
        """A refusal the app makes itself (the command that goes direct, for a person who is not signed in) has one hop of its own: its title names nobody as the server's do."""
        self.assertIn(f"'{hops.NOBODY}'", (STATIC / "js" / "turns.js").read_text())

    def test_the_actions_are_heard_from_the_pages_own_parent_from_a_lab_ui_origin_and_for_a_command_it_has(self):
        """A message the page acts on is the Lab UI's, for a command of the list: its source is the page's own parent, its origin one of the Lab UI's, its type
        and its id are what the contract says. Every check is made before anything runs, and nothing is run for what fails one."""
        actions = self.actions()
        heard = function_of(actions, "actionOf")
        order = ["event.source !== window.parent", "!LAB_ORIGINS.includes(event.origin)", ".type !== 'gravitee-lab:action'", "typeof message.id !== 'string'", "!ID.test(message.id)", "return message.id;"]
        self.assertEqual([heard.index(needle) for needle in order], sorted(heard.index(needle) for needle in order), "source, origin, type, id, then the id")
        self.assertIn("return null;", heard)
        wiring = function_of(actions, "initActions")
        self.assertIn("const id = actionOf(event);", wiring)
        self.assertLess(wiring.index("const id = actionOf(event);"), wiring.index("if (id) act(id, ports);"))
        self.assertEqual(len(re.findall(r"ports\.run\(", actions)), 1, "one way to run a command")
        self.assertRegex(actions, r"(?m)^const ID = /\^\[a-z0-9\]\[a-z0-9-\]\{0,63\}\$/;", "the shape of an id the Lab UI draws as a button")
        self.assertNotIn("'*'", actions)
        self.assertEqual(re.findall(r"https?://[^\s'\")]+", actions), [], "the origins are the one list of embed.js")
        act = function_of(actions, "act")
        self.assertIn("ports.run(command)", act)
        self.assertLess(act.index("ports.close()"), act.index("ports.run(command)"), "the sheet that covers the page is closed before the command runs")
        self.assertIn("close: () => closeSheet({ back: false })", actions, "and the focus is not taken from the guide")
        self.assertIn("ports.toast(", act, "an id the page does not know is told, not ignored")
        self.assertLess(act.index("ports.run(command)"), act.index("ports.toast("))
        self.assertIn("run: runCommand", actions)      # what a click on the command's own button runs

    def test_the_actions_run_the_command_as_its_button_does_and_the_page_says_it_is_ready_once_it_can(self):
        """The listener exists only when framed; the page says it is ready after it listens, and the commands are loaded by then, so that an action asked at once
        finds its command. The button of the rail runs the same function."""
        wiring = function_of(self.actions(), "initActions")
        self.assertLess(wiring.index("if (!embedded()) return;"), wiring.index("addEventListener('message'"))
        self.assertLess(wiring.index("addEventListener('message'"), wiring.index("tell({ type: 'gravitee-lab:ready' })"))
        self.assertEqual(wiring.count("tell("), 1)
        app = (STATIC / "app.js").read_text()
        start = function_of(app, "start")
        self.assertLess(start.index("loadCommands()"), start.index("initActions()"), "the commands are there before the page says it is ready")
        self.assertLess(start.index("initRouter()"), start.index("initActions()"))
        self.assertIn("onclick: () => runCommand(command)", (STATIC / "js" / "commands.js").read_text())

    def test_the_origins_the_page_posts_to_and_hears_are_one_list_and_the_one_the_policy_lets_frame_it(self):
        embed = self.embed()
        self.assertEqual(len(re.findall(r"^export const LAB_ORIGINS = ", embed, re.MULTILINE)), 1)
        self.assertEqual(re.findall(r"'([^']+)'", re.search(r"LAB_ORIGINS = \[([^\]]*)\]", embed).group(1)), security.LAB_UI.split())
        self.assertEqual(re.findall(r"https?://[^\s'\")]+", embed), security.LAB_UI.split(), "no other copy of them in the module")
        self.assertIn("for (const origin of parentOrigins())", function_of(embed, "tell"))
        self.assertIn("return LAB_ORIGINS;", function_of(embed, "parentOrigins"))
        self.assertNotIn("'*'", embed, "never to any origin")
        self.assertIn("import { LAB_ORIGINS, embedded, tell } from './embed.js';", self.actions())

    def test_framed_the_page_never_adds_an_entry_to_the_session_history(self):
        """A Back pressed inside another frame of the Lab UI (Gamma's own) goes back in the history the frames share: an entry the page added is one it
        would undo. Every change of view the page makes is a replacement, and a link to a view is taken in place when the page is framed."""
        router = (STATIC / "js" / "router.js").read_text()
        for path, script in scripts().items():
            self.assertNotIn("pushState", script, path)
            self.assertNotRegex(script, r"location\.(hash|href|assign)\s*=[^=]", f"{path}: a new address is a new entry")
            if path != "js/sign-in.js":
                self.assertNotIn("window.open(", script, f"{path}: the one window the page opens is the sign-in's")
        self.assertIn("history.replaceState(null, '', `#${view}`)", function_of(router, "go"))
        place = function_of(router, "inPlace")
        for needle in ("!embedded()", "event.preventDefault()", "history.replaceState(null, '', link.getAttribute('href'))", "a[href^=\"#\"]"):
            self.assertIn(needle, place)
        self.assertLess(place.index("event.preventDefault()"), place.index("history.replaceState"))
        self.assertIn("document.addEventListener('click', inPlace);", function_of(router, "initRouter"))

    def test_the_views_and_the_commands_hold_no_link_that_the_browser_would_follow_into_the_history(self):
        page = (STATIC / "index.html").read_text()
        for link in re.findall(r'<a [^>]*href="(#[^"]*)"', page):
            self.assertRegex(link, r"^#(assistant|teams|developers|presenter|commands|main|rail|inspector)?$", link)      # the one with none is Open Gamma: the page gives it the address of Gamma


class Modules(AppCase):
    """The page is modules, and a module that imports what another does not export stops the whole page: a browser says so only
    when someone opens it, so it is read here."""

    EXPORT = re.compile(r"^export (?:async )?(?:function|const|class) ([\w$]+)", re.MULTILINE)
    IMPORT = re.compile(r"^import \{([^}]+)\} from '([^']+)';", re.MULTILINE)

    def test_every_import_is_something_the_module_it_names_exports(self):
        sources = {"app.js": (STATIC / "app.js").read_text(), **{f"js/{p.name}": p.read_text() for p in (STATIC / "js").glob("*.js")}}
        for path, source in sources.items():
            for names, target in self.IMPORT.findall(source):
                resolved = (Path(path).parent / target).as_posix().removeprefix("./")
                self.assertIn(resolved, sources, f"{path} imports {target}")
                exported = set(self.EXPORT.findall(sources[resolved]))
                for name in (n.strip().split(" as ")[0] for n in names.split(",") if n.strip()):
                    self.assertIn(name, exported, f"{path} imports {name} from {target}")

    def test_no_module_imports_a_name_it_never_uses(self):
        for path, source in {**{"app.js": (STATIC / "app.js").read_text()}, **{f"js/{p.name}": p.read_text() for p in (STATIC / "js").glob("*.js")}}.items():
            for names, _ in self.IMPORT.findall(source):
                body = self.IMPORT.sub("", source)
                for name in (n.strip().split(" as ")[-1] for n in names.split(",") if n.strip()):
                    self.assertTrue(re.search(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])", body), f"{path} imports {name} and never uses it")

    def test_a_module_that_is_loaded_is_a_module_the_page_names(self):
        page = (STATIC / "index.html").read_text()
        self.assertRegex(page, r'<script type="module" src="app.js"></script>')
        self.assertNotRegex(page, r"<script(?![^>]*(type=\"module\"|src=\"theme.js\"))[^>]*src")

    def test_every_module_is_imported_by_the_page(self):
        """No module is left over: each is imported, directly or not, by app.js or by the entry script of follow.html or sign-in-done.html."""
        sources = {"app.js": (STATIC / "app.js").read_text(), **{f"js/{p.name}": p.read_text() for p in (STATIC / "js").glob("*.js")}}
        entries = ["app.js"]
        for name in ("follow.html", "sign-in-done.html"):
            entries += re.findall(r'<script type="module" src="/(js/[\w-]+\.js)"', (STATIC / name).read_text())
        reached, todo = set(), entries
        while todo:
            path = todo.pop()
            if path not in reached:
                reached.add(path)
                todo += [(Path(path).parent / target).as_posix().removeprefix("./") for _, target in self.IMPORT.findall(sources[path])]
        self.assertEqual(sorted(set(sources) - reached), [])


class Words(AppCase):
    """What a person reads and what the guide quotes (the views, the buttons), the routes and ids the page relies on, and the roles of its colors."""

    async def test_the_header_holds_only_what_is_global(self):
        """The header: the brand, the four views, the way into Gamma and the theme. Not a panel toggle, not a person, not the gateway, not
        Tokens: those belong to what they control (the commands' rail, the head of the conversation)."""
        page = (await self.http.get("/")).text
        header = re.search(r'<header class="topbar".*?</header>', page, re.DOTALL).group(0)
        nav = re.search(r'<nav class="nav".*?</nav>', header, re.DOTALL).group(0)
        self.assertEqual(re.findall(r'data-view="(\w+)"><span>([^<]+)</span>', nav),
                         [("assistant", "Assistant"), ("teams", "Teams"), ("developers", "Developers"), ("presenter", "Presenter")])
        self.assertEqual(re.findall(r'\bid="([\w-]+)"', header), ["topbar", "nav", "gamma-link", "theme", "more", "theme-menu"])
        # the bar of a phone: the commands are its first tab, the rest in the order of the header
        bar = re.search(r'<nav class="tabbar".*?</nav>', page, re.DOTALL).group(0)
        self.assertEqual(re.findall(r'data-view="(\w+)"><span data-icon="\w+"></span><span>([^<]+)</span>', bar),
                         [("commands", "Commands"), ("assistant", "Assistant"), ("teams", "Teams"), ("developers", "Developers"), ("presenter", "Presenter")])
        self.assertNotEqual(re.search(r'<nav class="nav"[^>]*aria-label="([^"]+)"', page).group(1), re.search(r'<nav class="tabbar"[^>]*aria-label="([^"]+)"', page).group(1))
        self.assertIn("Open Gamma", header)
        self.assertRegex(header, r'<a class="btn btn-platform" id="gamma-link"[^>]*data-gamma')

    async def test_who_is_asking_and_how_it_reaches_ace_are_in_the_head_of_the_conversation(self):
        page = (await self.http.get("/")).text
        head = re.search(r'<header class="stage-head" id="chat-head">.*?</header>', page, re.DOTALL).group(0)
        for needle in ('id="person-button"', 'id="gateway"', 'data-mode="off"', 'data-mode="on"', 'id="open-tokens"', "Choose who is asking",
                       "Direct", "Through the Gravitee gateway"):
            self.assertIn(needle, head, needle)

    async def test_the_views_have_the_buttons_the_guide_names(self):
        page = (await self.http.get("/")).text
        for label in ("Behind the answer", "Send money", "Short answer", "Long answer", "Long answer x3", "Send x10",
                      "Ask the cached FAQ twice", "Check", "Warm up", "Pause traffic", "Start the bank over", "Copy token"):
            self.assertIn(label, page + (await self.http.get("/js/commands.js")).text, label)

    async def test_every_route_the_page_calls_is_a_route_of_the_app(self):
        routes = {re.sub(r"\{\w+\}", "[^/]+", route.path) for route in self.app.routes if route.path.startswith("/api/")}
        called = set()
        for script in scripts().values():
            for path in re.findall(r"['`](/api/(?:[\w./-]|\$\{[^}]*\})+)", script):
                called.add(re.sub(r"\$\{[^}]*\}", "[^/]+", re.sub(r"(?<=[\w.-])\$\{[^}]*\}", "", path)))      # a placeholder after a name is a query string
        self.assertTrue(called)
        self.assertEqual(sorted(called - routes), [])

    async def test_every_id_of_the_page_is_unique(self):
        for name in ("index.html", "follow.html", "sign-in-done.html"):
            ids = re.findall(r'(?<![\w-])id="([^"]+)"', (STATIC / name).read_text())
            self.assertEqual(sorted({i for i in ids if ids.count(i) > 1}), [], name)

    async def test_the_page_follows_the_system_theme_and_a_choice_is_kept_without_depending_on_it(self):
        page, theme = (await self.http.get("/")).text, (await self.http.get("/theme.js")).text
        self.assertRegex(page, r'<script src="theme.js"></script>')  # not deferred: the theme is set before the page paints
        self.assertLess(page.index("theme.js"), page.index("app.js"))
        self.assertIn("try {", theme)
        self.assertIn("catch", theme)
        css = (STATIC / "style.css").read_text()
        self.assertIn("color-scheme: light dark", css)
        self.assertIn(':root[data-theme="dark"]', css)
        self.assertIn("light-dark(", css)
        header = (await self.http.get("/js/header.js")).text
        self.assertIn("catch { /* kept for this visit only */ }", header)

    async def test_neither_ink_is_ever_a_state_and_nothing_is_a_gradient(self):
        """Two inks with two jobs: the bank's indigo for the bank, the Gravitee orange for Gravitee (the way into Gamma, the gateway). A state
        is green, red, amber, blue, slate or neutral, never one of them, and the only gradients are the loading shimmer and the fade of a
        long text."""
        css = (STATIC / "style.css").read_text()
        states = (".chip", ".badge", ".hop", ".check", ".meter")
        for _, selector, body in rules(css):
            if any(re.search(rf"(^|[ ,>]){re.escape(name)}([.:\[ ,>]|$)", selector) for name in states) and ".a2a" not in selector and ".sel" not in selector:      # a selection is the bank's tint and ring, not a state
                self.assertNotRegex(body, r"var\(--(accent|bank)[\w-]*\)", selector)
        # a hop is neutral or a tone: nothing of it is Gravitee's but the mark on its evidence buttons
        self.assertNotIn("accent", declared(css, ".hop") + declared(css, ".hop .dot") + declared(css, ".badge") + declared(css, ".hop-summary"))
        for _, selector, body in rules(css):
            if "gradient(" in body:
                self.assertTrue(any(word in selector for word in (".skeleton", ".fades")), f"a gradient in {selector}")

    async def test_the_bank_is_indigo_and_gravitee_is_orange_and_they_never_swap(self):
        css = (STATIC / "style.css").read_text()
        for selector in (".btn-primary", ".logo-tile", ".logo-mark", ".skip", ".command .play"):
            body = declared(css, selector)
            self.assertRegex(body, r"var\(--(bank|on-bank)[\w-]*\)", selector)
            self.assertNotRegex(body, r"var\(--(accent|on-accent)[\w-]*\)", selector)
        for selector in (".btn-platform", ".gateway-option[aria-checked=\"true\"] svg.icon"):
            self.assertRegex(declared(css, selector), r"var\(--accent[\w-]*\)", selector)
        # the buttons of evidence are quiet: the color of a hop is its badge's, and Gravitee's is the way into its console and the busy mark
        self.assertNotIn("var(--accent", declared(css, ".evidence svg.icon") + declared(css, ".evidence:hover") + declared(css, ".evidence"))
        self.assertNotIn("var(--accent", declared(css, ".btn-primary") + declared(css, ":focus-visible") + declared(css, ".command"))
        self.assertNotIn("var(--accent", declared(css, ".hop-title") + declared(css, ".hop-summary") + declared(css, ".hop-details summary"))          # a title and a line are not links
        self.assertEqual(tokens(css)["--focus"], ("#1c1917", "#f5f4f2"), "the focus ring is neutral: the text color, not an ink")

    async def test_every_field_has_a_label(self):
        page = (await self.http.get("/")).text
        labeled = set(re.findall(r'<label[^>]*for="([^"]+)"', page))
        for tag in re.findall(r"<(?:input|textarea|select)\b[^>]*>", page):
            field_id = re.search(r'id="([^"]+)"', tag).group(1)
            self.assertTrue(field_id in labeled or "aria-label" in tag, field_id)

    async def test_every_button_that_shows_only_an_icon_is_named(self):
        page = (await self.http.get("/")).text
        for tag in re.findall(r'<button\b[^>]*class="[^"]*(?:icon-btn|(?<![-\w])send(?![-\w]))[^"]*"[^>]*>', page):
            self.assertIn("aria-label", tag)


class Look(AppCase):
    """The look of the page, read from its files: what a browser would show only by failing. How it looks is checked in a browser over
    `python -m tests.fake_stack` (see static/README.md)."""

    css = (STATIC / "style.css").read_text()

    def classes_of_the_stylesheet(self) -> set[str]:
        return set(re.findall(r"\.([a-zA-Z][\w-]*)", re.sub(r"/\*.*?\*/", "", self.css, flags=re.DOTALL)))

    def test_the_text_of_the_page_is_never_under_13_px(self):
        for size in re.findall(r"font(?:-size)?:\s*(\d+(?:\.\d+)?)px", re.sub(r"/\*.*?\*/", "", self.css, flags=re.DOTALL)):
            self.assertGreaterEqual(float(size), 13, f"a text of {size}px")
        self.assertRegex(self.css, r"--fs-1: 13px")

    def test_motion_gives_way_to_a_preference_and_the_waits_stay_readable(self):
        block = declared(self.css, "*, *::before, *::after", "(prefers-reduced-motion: reduce)")
        self.assertIn("animation-duration: .001ms !important", block)
        self.assertIn("transition-duration: .001ms !important", block)
        self.assertTrue(declared(self.css, ".spinner", "(prefers-reduced-motion: reduce)"))
        for _, _, body in rules(self.css):
            for duration in re.findall(r"(?<![\w-])(\d+)ms", body):
                self.assertLessEqual(int(duration), 220, "a motion is short")

    def test_forced_colors_keep_the_selections_and_the_meter(self):
        forced = "(forced-colors: active)"
        selectors = {part.strip() for m, sel, _ in rules(self.css) if m == forced for part in sel.split(",")}
        # in forced colors a selection is an outline, and each thing told by its color has a border or a system color
        for selector in (".gateway-option[aria-checked=\"true\"]", ".answer.sel", ".nav-link[aria-current=\"page\"]", ".tab[aria-current=\"page\"]",
                         ".meter", ".meter > i", ".msg.user .bubble", ".logo-tile", ".hop .stem", ".hop .dot", ".hop:not(.ok) .dot", ".chip", ".badge", ".evidence", ".msg.sel .reply", ".group-commands"):
            self.assertIn(selector, selectors, selector)
        self.assertIn("outline: 3px solid Highlight", declared(self.css, ".gateway-option[aria-checked=\"true\"], .mode-option[aria-checked=\"true\"], .nav-link[aria-current=\"page\"], .tab[aria-current=\"page\"]", forced))
        self.assertIn("forced-color-adjust: none", declared(self.css, ".meter > i", forced))      # the meter's fill is the one thing that must keep its own color

    def test_the_menu_of_a_phone_is_not_inside_anything_that_would_hold_it_off_the_screen(self):
        """A `position: fixed` menu is placed against the screen, unless an ancestor has a backdrop filter, a filter, a transform, a
        perspective, `contain`, `will-change` or is a container: then that ancestor is what it is placed against.
        The one menu that is fixed, the header's (the theme and, on a phone, Gamma), has none of them above it. The menus of the head of the stage (who is asking, the team)
        are dropdowns under their own button at every width, so the head is a container at every width, a phone's too."""
        holders = ("backdrop-filter", "-webkit-backdrop-filter", "filter", "transform", "perspective", "contain", "will-change", "container-type")
        for ancestor in (".topbar", ".topbar-inner", ".tools"):
            for _, selector, body in rules(self.css):
                if ancestor in [part.strip() for part in selector.split(",")]:
                    for holder in holders:
                        self.assertNotRegex(body, rf"(^|;|\s){holder}\s*:", f"{selector} has {holder}")
        for media in ("", "(max-width: 639px)"):
            self.assertNotIn("position: fixed", declared(self.css, ".person .menu", media), "the menus of the head open under their button, from the right edge")
        self.assertNotIn("container-type: normal", self.css, "the head is a container on a phone too: one set of steps")
        self.assertIn("container: head / inline-size", declared(self.css, ".stage-head"))
        phone = declared(self.css, "#theme-menu", "(max-width: 639px)")
        self.assertIn("position: fixed", phone)
        self.assertRegex(phone, r"bottom: calc\(var\(--tabbar-h\) \+ 12px")            # above the bar of views, inside the screen
        self.assertRegex(phone, r"left: var\(--s4\); right: var\(--s4\)")
        self.assertIn("max-height", phone)
        self.assertRegex(declared(self.css, ".menu"), r"max-height: calc\(100dvh")

    def test_a_short_screen_or_a_page_zoomed_to_400_percent_gives_the_height_back(self):
        short = "(max-height: 600px)"
        self.assertIn("position: static", declared(self.css, ".topbar", short))
        self.assertIn("--header-h: 0px", declared(self.css, ":root", short))
        self.assertIn("position: sticky", declared(self.css, ".tabbar", short))
        label = declared(self.css, ".tab span:last-child", short)
        self.assertIn("clip: rect(0 0 0 0)", label)               # the label of a view goes, its name stays (display: none would take it from a screen reader)
        self.assertNotIn("display: none", label)
        header = (STATIC / "js" / "header.js").read_text()
        self.assertIn("getComputedStyle(topbar).position === 'sticky'", header)        # the sticky things below clear nothing when the header goes with the page

    def test_the_targets_of_a_pointer_are_24_px_and_those_of_a_finger_44(self):
        self.assertIn("min-height: 24px", declared(self.css, ".link-button"))
        coarse = "(pointer: coarse)"
        listed = {part.strip() for m, sel, _ in rules(self.css) if m == coarse for part in sel.split(",")}
        for selector in (".btn", ".command", ".menu-item", ".link-button", ".evidence", ".nav-link", ".person-button", ".answer", ".icon-btn"):
            self.assertIn(selector, listed, selector)
        self.assertIn("min-height: 44px", " ".join(b for m, _, b in rules(self.css) if m == coarse))
        self.assertIn("width: 44px", declared(self.css, ".icon-btn", coarse))
        self.assertRegex(declared(self.css, ".command"), r"min-height: 4[0-9]px")             # and a command is a target of a pointer that is not a small one

    def test_a_field_has_a_border_that_is_seen_and_a_focus_that_is_too(self):
        self.assertIn("border: 1px solid var(--field-line)", declared(self.css, "input, select, textarea"))
        self.assertIn("var(--focus)", declared(self.css, ":focus-visible"))
        self.assertIn("border-color: var(--focus)", declared(self.css, "input:focus-visible, textarea:focus-visible"))     # not only a halo of a tint
        self.assertNotRegex(declared(self.css, "input:focus-visible, textarea:focus-visible"), r"outline:\s*none")

    def test_the_stylesheet_has_no_rule_for_a_class_nothing_uses(self):
        """Every class of the stylesheet is in the page or in a script."""
        used = (STATIC / "index.html").read_text() + (STATIC / "follow.html").read_text() + (STATIC / "sign-in-done.html").read_text() + "".join(p.read_text() for p in (STATIC / "js").glob("*.js")) + (STATIC / "app.js").read_text()
        used = re.sub(r"/\*.*?\*/|<!--.*?-->|^[ \t]*//[^\n]*|[ \t]//[ \t][^\n]*", "", used, flags=re.DOTALL | re.MULTILINE)        # a word in a comment is not a use
        for name in sorted(self.classes_of_the_stylesheet()):
            self.assertTrue(re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", used), f".{name} is in the stylesheet and nowhere else")

    def test_every_token_of_the_stylesheet_is_used(self):
        css = re.sub(r"/\*.*?\*/", "", self.css, flags=re.DOTALL)
        for token in sorted(set(re.findall(r"(--[\w-]+):", css))):
            self.assertRegex(css, rf"var\({re.escape(token)}[,)]", f"{token} is defined and never used")


class Structure(AppCase):
    """How the screens are put together, read from the markup and the scripts: the first screen, the commands as a list, the closed card of a
    payment, the one control that moves, the keyboard."""

    async def test_a_payment_is_a_mode_of_the_composer_and_its_box_is_never_a_dead_one(self):
        page = (await self.http.get("/")).text
        switch = re.search(r'<div class="modes" id="modes" role="radiogroup".*?</div>', page, re.DOTALL).group(0)
        self.assertEqual(re.findall(r'data-mode="(\w+)"[^>]*class="mode-option"><span data-icon="\w+"></span><span>([^<]+)</span>', switch),
                         [("ask", "Ask Ace"), ("pay", "Send money")])
        self.assertRegex(page, r'<form class="payform" id="money-form"[^>]*hidden>')   # the form of a payment is in the composer, and hidden until its mode
        self.assertNotRegex(page, r'<textarea id="message"[^>]*disabled', "where nobody is asking, Send opens the menu of who is asking")

    async def test_the_page_a_sign_in_ends_on_has_a_way_back_to_the_app_for_a_window_nothing_opened(self):
        page = (await self.http.get("/sign-in-done.html")).text
        self.assertRegex(page, r'<a class="btn" href="/">Back to ACME Bank</a>')
        self.assertNotRegex(page, r"<script(?![^>]*\bsrc=)", "and still no inline script")

    async def test_the_head_of_the_conversation_has_ace_and_the_route_at_the_left_and_tokens_then_the_person_at_the_right_end_in_the_order_of_the_keyboard(self):
        head = re.search(r'<header class="stage-head" id="chat-head">.*?</header>', (await self.http.get("/")).text, re.DOTALL).group(0)
        order = ['data-icon="ace"', "<h2>Ace</h2>", 'id="gateway"', 'class="head-end"', 'id="open-tokens"', 'id="person"', 'id="person-button"']
        self.assertEqual([head.index(needle) for needle in order], sorted(head.index(needle) for needle in order), "Ace, its name, the route, then Tokens, then the person")
        end = head[head.index('class="head-end"'):]
        self.assertLess(end.index('id="open-tokens"'), end.index('id="person"'))
        css = (STATIC / "style.css").read_text()
        self.assertIn("margin-left: auto", declared(css, ".stage-head > .person, .stage-head .head-end"), "pushed to the right end, as an account is on any site")
        self.assertIn("flex-wrap: nowrap", declared(css, ".stage-head"), "one row at every width")
        self.assertNotRegex(css, r"\.gateway\s*\{\s*order", "the route does not jump to a second row")

    async def test_what_the_head_gives_up_as_its_room_goes_is_one_list_of_steps_for_every_width_a_phone_included(self):
        css = re.sub(r"/\*.*?\*/", "", (STATIC / "style.css").read_text(), flags=re.DOTALL)
        container = [int(width) for width in re.findall(r"@container head \(max-width: (\d+)px\)", css)]
        self.assertTrue(container)
        self.assertEqual(container, sorted(container, reverse=True), "from the first to give way to the last")
        self.assertNotRegex(css, r"@media[^{]*\{[^}]*(?:asking-label|person-text|gateway-full|gateway-option \{ padding)", "no step of the head is by the width of the page")

    async def test_the_menus_of_the_head_open_from_the_right_edge_and_stay_in_the_viewport(self):
        css = (STATIC / "style.css").read_text()
        self.assertNotRegex(declared(css, ".person .menu"), r"left:\s*0", "the person is at the right end: its menu opens from there")
        self.assertIn("min(360px, calc(100vw - 4 * var(--s4)))", declared(css, ".person .menu"), "inside the viewport, the page's and the head's margins left")
        self.assertIn("margin: 0 0 0 auto", declared(css, "dialog.drawer"), "the drawer of the token comes from the right edge")

    async def test_the_commands_are_a_list_of_groups_with_a_heading_each(self):
        commands = (STATIC / "js" / "commands.js").read_text()
        group = function_of(commands, "groupNode")
        self.assertIn("h('h3', { class: 'group-title', id }", group)                           # a heading for each group: a screen reader moves from one to the next
        self.assertIn("' ', h('span', { text: group.title })", group)                          # "1 See everything", not "1See everything", to a screen reader
        self.assertIn("aria-labelledby", group)
        node = function_of(commands, "commandNode")
        self.assertIn("who ? `${command.label}, as ${who}` : command.label", node)            # the button says for whom it runs
        self.assertIn("state.groups.map(groupNode)", function_of(commands, "build"))          # every group, whole: none is open or closed

    async def test_the_browser_bar_follows_the_theme(self):
        page = (await self.http.get("/")).text
        self.assertEqual(len(re.findall(r'<meta name="theme-color"', page)), 2)
        self.assertIn("prefers-color-scheme: dark", re.findall(r'<meta name="theme-color"[^>]*>', page)[1])

    async def test_the_keyboard_has_a_way_past_the_header(self):
        page = (await self.http.get("/")).text
        self.assertIn('<a class="skip" href="#main">', page)
        self.assertIn('<a class="skip" href="#rail">Skip to the commands</a>', page)
        self.assertRegex(page, r'<aside class="rail" id="rail"[^>]*tabindex="-1"')


# What the stylesheet draws with a pseudo-element, and why each is not an accent: the reset, the turning mark of a button that is looking, the tick of the half of a
# budget. The rail of the hops draws none: it is made of elements of the rows.
FUNCTIONAL_PSEUDO = {"*::before", "*::after", '.evidence[aria-busy="true"]::before', ".meter.half::after"}


class TheLook(AppCase):
    """What the stylesheet must keep so that the page reads in the right panel of the Lab UI (a window of 640 to 1280 px): the line that joins the hops, the
    evidence under the answer, the one breakpoint of the phone."""

    css = (STATIC / "style.css").read_text()

    def test_the_rail_of_the_hops_is_made_of_elements_of_the_rows_so_that_its_lines_always_join(self):
        """The stems of two rows must be one line. The rail is the first column of each row: a stem as tall as the row (an element, not a pseudo-element placed by
        an offset that depends on what the row holds) and a dot on it. Rows touch, nothing is added between them, and the rail is the same for every kind of hop.
        The geometry of every kind of hop is checked in a browser (see static/README.md)."""
        self.assertEqual(declared(self.css, ".timeline").count("gap: 0"), 1, "no space between rows: the stems of two rows meet")
        hop = declared(self.css, ".hop")
        for needed in ("display: grid", "grid-template-columns: 20px minmax(0, 1fr)"):
            self.assertIn(needed, hop)
        self.assertNotRegex(hop, r"(margin|padding)", "a row is its rail and its content: the room between two hops is inside the content, so the rail does not stop")
        self.assertIn("position: relative", declared(self.css, ".hop-rail"))
        stem = declared(self.css, ".hop .stem")
        for needed in ("position: absolute", "left: 9px", "width: 2px", "top: 0", "bottom: 0"):          # as tall as the row, from its top to its bottom
            self.assertIn(needed, stem)
        self.assertIn("top: var(--dot-y)", declared(self.css, ".hop:first-child .stem"))                   # the first row's stem starts at its dot ...
        self.assertIn("bottom: calc(100% - var(--dot-y))", declared(self.css, ".hop:last-child .stem"))    # ... and the last row's ends there
        self.assertIn("display: none", declared(self.css, ".hop:only-child .stem"))
        dot = declared(self.css, ".hop .dot")
        self.assertIn("left: 4px", dot)                                       # 4 + 12 / 2 = 9 + 2 / 2: the dot is centered on the stem
        self.assertIn("--dot: 12px", hop)
        self.assertIn("top: calc(var(--dot-y) - var(--dot) / 2)", dot)       # and centered on the same line as the title's first line, in every row
        self.assertIn("padding-bottom: var(--s5)", declared(self.css, ".hop-main"))
        self.assertIn("padding-bottom: 0", declared(self.css, ".hop:last-child .hop-main"))
        for tone in ("deny", "block", "limit", "error"):                      # a hop that went wrong changes the color of its dot and nothing of its shape
            self.assertRegex(declared(self.css, f".hop.{tone}"), r"^--tone: var\(--[\w-]+-line\);$", tone)

    def test_the_rail_is_built_the_same_for_every_hop_by_the_one_function_that_draws_a_hop(self):
        script = (STATIC / "js" / "inspector.js").read_text()
        node = function_of(script, "hopNode")
        self.assertEqual(node.count("class: 'hop-rail'"), 1)
        self.assertIn("h('span', { class: 'stem' }), h('span', { class: 'dot' })", node)
        self.assertIn("aria-hidden", node)                                    # the rail is for the eye: the list says the order
        self.assertNotIn("tone ===", node, "no kind of hop has a rail of its own")

    def test_only_a_refused_status_is_loud_and_the_three_badges_stay_on_one_line(self):
        """The system, the status and the time of a hop are badges, all neutral but the status of a call that did not go through, which is the tone of what happened and
        has a mark of its own (the page draws it) so that its color is not what says it."""
        badge = declared(self.css, ".badge")
        self.assertIn("white-space: nowrap", badge)
        self.assertNotRegex(badge, r"var\(--(ok|deny|warn|info|block|trouble)")
        for tone, ink in (("deny", "deny"), ("block", "block"), ("limit", "warn"), ("error", "trouble")):
            loud = declared(self.css, f".badge.status.{tone}")
            for token in (f"--{ink}-bg", f"--{ink}-line", f"--{ink})"):
                self.assertIn(token, loud + ")", f"{tone}: {token}")
        self.assertEqual(declared(self.css, ".badge.status.ok"), "", "what went as it should is a neutral badge")
        self.assertIn("border-style: dashed", declared(self.css, ".badge.system.direct"))     # a call with no gateway says it by its outline too
        # the three are on one line at every width: the system, which is only a name, gives way (ellipsis, its full name in its title), the status and the time do not
        self.assertNotIn("wrap", declared(self.css, ".badges"))
        self.assertRegex(declared(self.css, ".badge"), r"flex: none")
        self.assertRegex(declared(self.css, ".badge.system"), r"flex: 0 1 auto; min-width: 0")
        self.assertIn("text-overflow: ellipsis", declared(self.css, ".badge.system > span"))
        for selector in (".badge", ".hop-title", ".hop-summary", ".hop-details summary"):
            self.assertNotIn("sticky", declared(self.css, selector))

    def test_the_hidden_word_of_a_badge_cannot_make_the_page_scroll(self):
        """The screen-reader word of a status (`.sr` is absolutely placed) sits in the badge, which is its containing block: the scrolling column of the hops clips what is
        placed in it. Placed against the page instead, a hop below the fold would make the whole page taller than the screen."""
        self.assertIn("position: relative", declared(self.css, ".badge"))
        self.assertIn("position: absolute", declared(self.css, ".sr"))
        self.assertIn("overflow-y: auto", declared(self.css, ".behind-body"))
        self.assertIn("h('span', { class: 'sr', text: ` ${word}` })", (STATIC / "js" / "ui.js").read_text())          # the word is in the badge

    def test_the_buttons_of_evidence_wrap_in_a_narrow_column(self):
        self.assertIn("evidenceButtons(row.evidence, row.title)", function_of((STATIC / "js" / "inspector.js").read_text(), "hopNode"))
        self.assertIn("display: flex", declared(self.css, ".hop-evidence"))
        self.assertIn("flex-wrap: wrap", declared(self.css, ".hop-evidence"))                      # three buttons do not run out of a column of 270 px

    def test_the_commands_are_beside_the_stage_from_640_px_and_a_tab_below(self):
        self.assertIn("(max-width: 639px)", (STATIC / "js" / "store.js").read_text())
        self.assertIn('"rail main"', declared(self.css, '.shell[data-view="assistant"], .shell[data-view="teams"]', "(min-width: 640px)"))
        self.assertIn("--rail-w: 240px", declared(self.css, '.shell[data-view="assistant"], .shell[data-view="teams"]', "(min-width: 640px) and (max-width: 899px)"))
        self.assertIn("display: none", declared(self.css, ".nav", "(max-width: 639px)"))


class Rules(AppCase):
    """Rules that hold at every width and in every view: the keyboard, the order of the evidence, where the controls are, what scrolls."""

    async def test_behind_the_answer_has_a_control_only_where_it_is_a_sheet(self):
        css = (STATIC / "style.css").read_text()
        self.assertIn("display: none", declared(css, ".hops-open"))                                     # the control is not there ...
        self.assertIn("display: inline-flex", declared(css, ".msg.sel .hops-open, .answer.sel .hops-open", "(max-width: 1279px)"))      # ... but under the selected answer where Behind the answer is a sheet
        self.assertEqual(declared(css, ".msg.sel .hops-open"), "")                                       # and never beside the stage, from 1280 px
        self.assertIn("display: none", declared(css, ".stage-head #open-tokens:disabled"))              # nobody is asking: no token to show, and the room is the route's
        self.assertIn("matchMedia('(min-width: 1280px)')", (STATIC / "js" / "store.js").read_text())    # the inspector is docked from 1280 px: the sheet and the control share the line
        for name in ("chat.js", "money.js", "teams.js", "developers.js"):
            script = (STATIC / "js" / name).read_text()
            for made in re.findall(r"h\('button', \{[^}]*Behind the answer[^}]*\}", script):
                self.assertIn("hops-open", made, f"{name}: a control for Behind the answer that wide screens still show")

    async def test_the_logs_are_not_a_tab_stop(self):
        """A log that can be focused is a stop with nothing to do on it; a screen reader reads it with its virtual cursor and a
        keyboard user reaches the answers through the controls in them."""
        page = (await self.http.get("/")).text
        for log in re.findall(r'<div[^>]*role="log"[^>]*>', page):
            self.assertNotIn("tabindex", log)
        self.assertEqual(len(re.findall(r'role="log"', page)), 3)
        for name in ("chat.js", "teams.js", "developers.js", "turns.js"):
            script = (STATIC / "js" / name).read_text()
            self.assertNotRegex(script, r"(box|feed|log)\(\)\.(setAttribute\('tabindex'|tabIndex)", name)
        css = (STATIC / "style.css").read_text()
        for selector in (".conversation:focus-visible", ".conversation:focus", ".feed:focus-visible", ".feed:focus", "[role=\"log\"]:focus-visible"):
            self.assertNotIn(selector, css, selector)

    async def test_the_evidence_is_in_one_order_everywhere(self):
        """Trace, Logs, Decisions, Spend: a person finds each where it was."""
        order = ["trace", "logs", "decisions", "spend"]
        ui = (STATIC / "js" / "ui.js").read_text()
        self.assertEqual(re.findall(r"'(\w+)'", re.search(r"export const EVIDENCE_ORDER = \[(.*?)\];", ui).group(1)), order)
        self.assertIn("EVIDENCE_ORDER.map", ui)
        self.assertIn("ordered(items)", function_of(ui, "evidenceButtons"))
        shuffled = answers.evidence(spend="s", decisions="d", logs="l", trace="t")
        self.assertEqual([e["kind"] for e in shuffled], order)
        self.assertEqual([e["label"] for e in shuffled], ["Trace", "Logs", "Decisions", "Spend"])
        self.assertEqual([e["kind"] for e in answers.evidence(decisions="d", trace="t")], ["trace", "decisions"])      # one that is not there leaves the others where they were
        self.assertEqual([e["kind"] for e in answers.evidence(logs="l", decisions=None)], ["logs"])

    async def test_below_1280_px_behind_the_answer_is_a_modal_dialog_and_what_is_behind_it_is_inert(self):
        page = (await self.http.get("/")).text
        self.assertEqual(page.count('id="behind"'), 1)                      # one inspector for the three views, not one per view
        inspector = (STATIC / "js" / "inspector.js").read_text()
        self.assertIn("aria-modal", inspector)
        self.assertIn("inert", inspector)

    async def test_the_notices_have_one_place_at_every_width_over_the_header_never_over_the_composer_or_the_commands(self):
        css = (STATIC / "style.css").read_text()
        toasts = declared(css, ".toasts")
        self.assertRegex(toasts, r"top: calc\(var\(--s3\)")
        self.assertNotRegex(toasts, r"(^|[\s;])(bottom|right)\s*:", "not at the bottom, where the composer is, nor at a side, where the commands are or Behind the answer is")
        self.assertEqual([m for m, selector, _ in rules(css) if selector == ".toasts"], [""], "one rule, no other place at another width")

    async def test_a_scroller_scrolls_its_rows_do_not_shrink_to_fit_it(self):
        """The answers of a feed and the turns of a conversation keep their own height: a column that is given less room than its rows
        need squeezes them to nothing (a phone with a band over the answers did) unless each row is told not to shrink."""
        css = (STATIC / "style.css").read_text()
        for scroller in (".feed > *", ".conversation > *"):
            self.assertIn("flex: none", declared(css, scroller), scroller)

    async def test_the_head_of_the_rail_stays_the_rest_scrolls_and_cannot_scroll_sideways_and_the_foot_ends_the_list(self):
        css = (STATIC / "style.css").read_text()
        self.assertIn("overflow: hidden", declared(css, ".rail"))                    # the rail does not scroll: its list does
        groups = declared(css, ".groups")
        self.assertIn("overflow-y: auto", groups)
        self.assertIn("overflow-x: hidden", groups)                                  # a slip of a pixel is not a scrollbar over the commands
        self.assertIn("flex: none", declared(css, ".commands-head"))
        foot = declared(css, ".rail-foot")
        self.assertIn("margin-top: auto", foot)                                      # at the bottom where the list is short, at the end of it where it is long: never over a command
        self.assertNotIn("sticky", foot)
        self.assertNotIn("fixed", foot)

    async def test_no_card_notice_toast_or_bubble_wears_a_bar_on_one_edge(self):
        """What is selected or went wrong is told by a tint, a ring all round, a chip and a word, never by a colored bar on one side. A one-sided line is a hairline
        of a neutral ink (a divider, the edge of a panel), and a pseudo-element draws no accent."""
        css = re.sub(r"/\*.*?\*/", "", (STATIC / "style.css").read_text(), flags=re.DOTALL)
        neutral = re.compile(r"var\(--(line|line-strong)\)")
        for _, selector, body in rules(css):
            for declaration in re.findall(r"border-(?:left|right|top|bottom|inline-start|inline-end|block-start|block-end)\s*:[^;]+", body):
                if not re.search(r"\s0\s*$|none$", declaration.strip()):
                    self.assertTrue(neutral.search(declaration), f"a colored line on one edge of {selector}: {declaration}")
            for shadow in re.findall(r"box-shadow\s*:[^;]+", body):
                self.assertNotRegex(shadow, r"inset\s+(?:-?[1-9][\d.]*px\s+-?[\d.]+px|-?[\d.]+px\s+-?[1-9][\d.]*px)\s+0\s+(?!0)", f"a bar of shadow on one edge of {selector}: {shadow}")
                if "inset" in shadow:      # a shadow inside is a ring all round: the same width on every side
                    self.assertRegex(shadow, r"inset\s+0\s+0\s+0\s+[\d.]+px", f"{selector}: {shadow}")
                if re.search(r"(^|\s)0\s+-?[1-9][\d.]*px\s+0\s", shadow):       # a hairline between two rows is the only line a shadow draws on one side
                    self.assertTrue(neutral.search(shadow), f"{selector}: {shadow}")
            for part in selector.split(","):
                if "::before" in part or "::after" in part:
                    self.assertIn(part.strip(), FUNCTIONAL_PSEUDO, f"{part.strip()} draws something: a bar on an edge is not one of the lines the page needs")

    async def test_the_focus_ring_of_a_command_is_inside_its_card_which_clips_what_is_outside(self):
        css = (STATIC / "style.css").read_text()
        self.assertIn("outline-offset: -3px", declared(css, ".command:focus-visible"))
        self.assertIn("overflow: hidden", declared(css, ".group-commands"))


FAMILIES = ("ok", "deny", "warn", "info", "block", "slate", "trouble")       # the families of a tone, each with ink and bg tokens
LINED = tuple(name for name in FAMILIES if name != "slate")                  # and a line (a stroke that has to be seen) for those the page strokes: not slate, which only tints a chip


class Colors(AppCase):
    """What the page reads, light and dark: text on what it is laid on at 4.5 to 1, and what is not text (the border of a field, the ring of
    the focus, the stroke of a state) at 3 to 1. Each pair is computed from the tokens of the stylesheet."""

    TEXT = (
        *[(front, back) for front in ("--text", "--text-2", "--text-3") for back in ("--surface", "--bg", "--surface-2", "--surface-3", "--raised")],
        ("--accent", "--surface"), ("--accent", "--bg"), ("--accent", "--surface-2"), ("--accent", "--accent-soft"), ("--accent", "--raised"),
        ("--on-bubble-user", "--bank-tint"),
        # the bank's indigo: as a link or an icon on every surface, on its own tints, and under the white or dark text of a solid button
        *[("--bank", back) for back in ("--surface", "--bg", "--surface-2", "--surface-3", "--raised", "--bank-soft", "--bank-tint")],
        ("--on-bank", "--bank-fill"), ("--on-bank", "--bank-hover"), ("--text", "--bank-soft"), ("--text", "--bank-tint"),
        # a state is told in words on a card: the ink of the neutral cards on their own tint
        ("--text-2", "--surface-2"),
        # a family's ink on its own tint (a chip, a callout), on a card, and on the well of a card
        *[(f"--{name}", back) for name in FAMILIES for back in (f"--{name}-bg", "--surface", "--surface-2")],
        *[("--text", f"--{name}-bg") for name in FAMILIES], ("--text", "--accent-soft"),
        ("--text-2", "--warn-bg"), ("--text-2", "--info-bg"),
    )
    NON_TEXT = (
        ("--field-line", "--surface"), ("--field-line", "--surface-2"), ("--field-line", "--bg"),
        ("--focus", "--surface"), ("--focus", "--bg"), ("--focus", "--surface-2"), ("--focus", "--raised"),
        ("--accent", "--surface"),
        ("--bank-fill", "--surface"), ("--bank-fill", "--bg"),
        # what is selected is told by a hairline ring where it sits: on the stage, on its own tint and on the tint of each state
        *[("--select-line", back) for back in ("--surface", "--bg", "--surface-2", "--bank-soft", *[f"--{name}-bg" for name in FAMILIES])],
        # a control that has to be found is bounded by a line that is seen: the gateway control
        ("--accent", "--bg"),
        *[(f"--{name}-line", "--surface") for name in LINED], *[(f"--{name}-line", f"--{name}-bg") for name in LINED],
        # the dot of a hop that did not go through, and the stem of the rail, on the page beside the stage and on the card of the sheet
        *[(f"--{name}-line", "--bg") for name in LINED], ("--field-line", "--bg"),
    )

    def ratio(self, front: str, back: str, theme: int) -> float:
        found = tokens((STATIC / "style.css").read_text())
        return contrast(hex_of(found[front][theme]), hex_of(found[back][theme]), hex_of(found["--surface"][theme]))

    def test_the_text_of_the_page_reads_in_both_themes(self):
        for front, back in self.TEXT:
            for theme in (0, 1):
                self.assertGreaterEqual(self.ratio(front, back, theme), 4.5, f"{front} on {back}, {('light', 'dark')[theme]}: {self.ratio(front, back, theme):.2f}")

    def test_what_is_not_text_but_has_to_be_seen_reads_in_both_themes(self):
        for front, back in self.NON_TEXT:
            for theme in (0, 1):
                self.assertGreaterEqual(self.ratio(front, back, theme), 3.0, f"{front} on {back}, {('light', 'dark')[theme]}: {self.ratio(front, back, theme):.2f}")

    def test_every_token_a_pair_names_exists_and_every_family_has_all_its_tokens(self):
        found = tokens((STATIC / "style.css").read_text())
        for name in FAMILIES:
            for part in ("", "-bg", *(("-line",) if name in LINED else ())):
                self.assertIn(f"--{name}{part}", found)
        for token in ("--accent", "--accent-soft", "--focus", "--field-line",
                      "--bank", "--bank-fill", "--bank-hover", "--on-bank", "--bank-soft", "--bank-tint", "--bank-line", "--select-line"):
            self.assertIn(token, found)

    def test_the_helpers_of_this_test_say_what_they_should(self):
        self.assertAlmostEqual(contrast(hex_of("#000000"), hex_of("#ffffff"), hex_of("#ffffff")), 21, places=0)
        self.assertAlmostEqual(contrast(hex_of("#777777"), hex_of("#ffffff"), hex_of("#ffffff")), 4.48, places=1)
        # a pair under 4.5 to 1 is one this test catches
        self.assertLess(contrast(hex_of("#4a5df0"), hex_of("#121a33"), hex_of("#121a33")), 4.5)
        self.assertEqual(rules("a, b { c: d } @media (x) { e { f: g } }"), [("", "a, b", "c: d"), ("(x)", "e", "f: g")])

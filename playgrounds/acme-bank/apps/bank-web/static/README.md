# The page

Plain HTML, CSS and JavaScript modules: no framework, no build step, nothing loaded from outside. The app serves this
folder as it is.

## Files

- `index.html` is the page. `follow.html` is the small page a followed evidence link opens, and `sign-in-done.html` is the
  page the window of a sign-in ends on. `style.css` is the whole stylesheet.
- The two entry scripts are at the root, and the modules are in `js/`:
  - `app.js` is a module that starts the page.
  - `theme.js` is a classic script in the `<head>`, not a module: a module is deferred, so the page would paint before the
    theme was set. It sets `data-theme` from the saved choice before the first paint, and does nothing where storage is
    refused.
- Modules, by role:
  - Base: `dom.js` (node builder, API call, event bus), `store.js` (who asks, the turns and the selection, the one flag that
    says something is running), `icons.js` (drawn icons), `ui.js` (badges, evidence buttons, notices, a model's text),
    `richtext.js` (what an answer is made of), `clipboard.js`, `menus.js`.
  - Views: `chat.js`, `composer.js`, `money.js`, `teams.js`, `developers.js`, `presenter.js`, `commands.js` (the rail and the
    run of a command), `bank.js` (start the bank over), `tokens.js`.
  - Behind the answer: `inspector.js` (the hops, and the sheet it becomes), `turns.js` (what the three conversations share),
    `monitor.js` (the budget and the tokens left).
  - Page: `router.js` (views, history, the rail's edge control), `header.js`, `asking.js` (the route and the menu of who is
    asking), `session.js` (who asks and who is signed in), `sign-in.js` (the window of a sign-in), `sign-in-done.js`.
  - Gamma and the Lab UI: `embed.js` (where to go in Gamma, how to speak to the Lab UI), `actions.js` (the guide's actions),
    `lookup.js` and `follow.js` (looking for the item of a call).
  - Plain functions: `words.js` (the page's sentences), `errors.js` (what a failure says), `wait.js` (a way out of a wait).

## Rules to keep

- The content security policy allows nothing inline: no script in the page, no `style` attribute (a value that depends on a
  number is set on the node's style object), nothing from another origin.
- A server's text is set with `textContent` or built as nodes, never as markup. No `innerHTML`, `eval` or `document.write`.
- Framed by the Lab UI, the page never adds an entry to the session history: no `pushState`, no assignment to
  `location`, and a link to a view is taken in place.
- Every module is imported by the page, every import resolves and is used, every class and token of the stylesheet is used.
- What the page keeps in the browser (the theme, whether the rail is open) is a convenience: it works with none of it.
- The colors are `light-dark()` tokens with no fallback: Chrome or Edge 123, Firefox 120 or Safari 17.5, or later.

## The look

Calm and flat: a neutral canvas, hairlines instead of shadows, and a shadow only on what floats. The tokens are at the top of
`style.css`, and every color is one that follows the system theme (`light-dark()`); the dark theme is its own set.

- **Contrast.** Text is 4.5 to 1 or more on every surface it sits on, and what is not text but has to be seen (the border of
  a field, the focus ring, the stroke of a state) is 3 to 1, in both themes. A test computes each pair from the tokens.
- **Inks.** `--bank` (indigo) is the bank's: its logo, buttons, links and the person's own words. `--accent` (orange) is
  Gravitee's only: **Open Gamma** and the gateway. Neither is ever a state, and the focus ring (`--focus`) is neutral.
- **Tones.** `--ok`, `--deny`, `--warn`, `--info`, `--block`, `--slate` and `--trouble`, each with `-bg` (a tint) and, but the
  slate, `-line` (a stroke). What a call did is told by a word and a mark as well as a color.
- **Selection.** The selected answer is on a neutral well (`--surface-2`) with a hairline ring (`--select-line`), so it never
  looks like something the person said. No card, notice or bubble draws a colored bar on one edge. In forced colors a
  selection is a 3 px `Highlight` outline.
- **Type.** A system stack (`--font`, `--mono`), a scale `--fs-1` to `--fs-9` with nothing under 13 px, tabular figures,
  prose held to 66 characters.
- **Space and motion.** A 4 px grid (`--s1` to `--s5`), radii by role, motion of 220 ms at most that gives way to
  `prefers-reduced-motion`.
- **Targets.** 24 px at least, 44 px for a finger (`pointer: coarse`); every control has a focus ring.
- **Layout.** Three columns on a wide screen (the commands, the stage, Behind the answer), each scrolling inside itself. The
  commands are a rail from 640 px; Behind the answer is docked from 1280 px and a sheet below. Under 640 px the views are a
  bar at the bottom and the page scrolls. A short screen (a phone on its side, a page zoomed to 400%) lets the header go
  with the page. The notices sit at the top in the middle at every width.
- **Menus.** A `position: fixed` menu is placed against the screen only if none of its ancestors has a filter, a transform,
  `contain`, `will-change` or a container, so the header has none. The menus of the head of the stage are dropdowns.
- **Keyboard and screen reader.** Three links skip to the content, the commands and Behind the answer. One polite live
  region (`#announcer`) says an answer, a wait and a failure. A log is not a tab stop. A command that waits is
  `aria-disabled`, not `disabled`, so the focus stays where it was. Behind the answer as a sheet is a modal dialog: the rest
  of the page is `inert`, Tab stays inside, and Escape returns the focus to the control that opened it.

## Looking at it

`tests/test_page.py` reads these files for the rules above. To look at the page, serve the app over the fakes of the tests
and walk its API:

```bash
python -m tests.fake_stack 8139 off=guard,tools,pep,cap,router &
python tests/smoke.py http://localhost:8139
```

- `off=` starts those protections switched off, as the lab does; leave it out for all on.
- `slow=2` makes Ace take two seconds to answer, `fail=ace` has the gateway answer 504 to Ace, and `down=apim` has the
  management API not answer, so the evidence cannot be looked up.
- The fake Access Management login page is on the next port (8140) and signs the person in at once. In a container,
  `HOST=0.0.0.0` lets a published port reach it.
- `tests/smoke.py` also runs against the playground, `python tests/smoke.py http://localhost:8110`: each person signs in at
  the login page of Access Management with the demo password the page lists. It moves EUR 120 from Alice to Bob and back.

Check the states in a browser at 390, 768, 960, 1280, 1440 and 1664 px, in both themes, with forced colors and reduced
motion, at 320 px, and on a short screen.

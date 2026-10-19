/* Which view is showing. The address says it: #assistant, #teams, #developers, #presenter. The commands are beside the Assistant and Teams; on a phone, where
   nothing sits beside the conversation, they are a tab of the bar at the bottom: #commands.
   Framed by the Lab UI the page never adds an entry to the session history: a Back pressed in another frame of the Lab UI (Gamma's own) goes back in the
   history the frames share, and an entry made here is one it would undo. A change of view is a replacement of the address, never a new one. Standalone a link
   to a view is a link, and the browser's Back goes back between views. */
import { $, $$, bus, storage } from './dom.js';
import { embedded } from './embed.js';
import { state, DOCKED, PHONE } from './store.js';

const VIEWS = ['assistant', 'commands', 'teams', 'developers', 'presenter'];
const NAMES = { assistant: 'Assistant', commands: 'Commands', teams: 'Teams', developers: 'Developers', presenter: 'Presenter' };
const WITH_COMMANDS = ['assistant', 'teams'];
const SKIPS = ['main', 'rail', 'inspector'];       // the targets of the skip links: they are places on the page, not views

/* Whether a place of the page is there to be skipped to: the commands are beside the Assistant and Teams (a tab of their own on a phone), Behind the
   answer is beside the stage where it is docked. A skip link to a place that is not shown goes nowhere, so it is not offered. */
const placeShown = (target, view = state.view) => (target === 'main' ? true
  : target === 'rail' ? (PHONE.matches ? view === 'commands' : WITH_COMMANDS.includes(view))
    : !PHONE.matches && DOCKED.matches && ['assistant', 'teams', 'developers'].includes(view));

function offerSkips() {
  for (const link of $$('.skip')) link.hidden = !placeShown(link.getAttribute('href').slice(1));
}

export function show(view, { focus = false } = {}) {
  if (view === 'commands' && !PHONE.matches) view = 'assistant';
  state.view = view;
  $('#shell').dataset.view = view;
  for (const section of $$('.view')) section.hidden = section.dataset.view !== view;
  for (const link of $$('.nav-link[data-view], .tab[data-view]')) {
    if (link.dataset.view === view) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  document.title = view === 'assistant' ? 'ACME Bank' : `${NAMES[view]} · ACME Bank`;
  if (focus) {
    const heading = $(`#view-${view} h1`) || $('#rail h2');
    if (heading) { heading.tabIndex = -1; heading.focus({ preventScroll: true }); }
  }
  offerSkips();
  bus.emit('view', view);
}

/* Leaves the history as it is: the page changes the view for a command, the person did not navigate. `focus`: the person chose to go there (a link), so the
   view's heading takes the focus. */
export function go(view, { focus = false } = {}) {
  if (!PHONE.matches && view === 'commands') view = 'assistant';
  if (location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
  show(view, { focus });
}

function applyHash(first = false) {
  const hash = location.hash.replace(/^#/, '');
  if (SKIPS.includes(hash)) {                       // a skip link's address is no view: the person stays where they are
    if (first) show('assistant');
    return;
  }
  show(VIEWS.includes(hash) ? hash : 'assistant', { focus: !first });
}

/* Framed, a click on a link to a view changes the address in place: the link does what it says and leaves the history alone. */
function inPlace(event) {
  if (!embedded() || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const link = event.target && event.target.closest ? event.target.closest('a[href^="#"]') : null;
  if (!link) return;
  event.preventDefault();
  history.replaceState(null, '', link.getAttribute('href'));
  applyHash();
}

/* ---- the commands' own edge control: open, or a slim strip ----------------------------------------------------------------- */

/* What the person chose in this mode, else the mode decides. Standalone the commands are open: a first visit sees them (below 1280 px Behind the answer is a
   sheet, which leaves the stage the room the commands take). Framed by the Lab UI they are the slim strip, one click from open: the guide has buttons that run
   them. The page has one origin in both modes, so each mode keeps its own choice: a choice made in a tab of its own does not decide for the Lab UI. */
const railKey = () => (embedded() ? 'rail-in-lab' : 'rail');
const chosenRail = () => { const kept = storage.read(railKey(), null); return typeof kept === 'boolean' ? kept : null; };
export const railWanted = () => { const kept = chosenRail(); return kept === null ? !embedded() : kept; };

function setRail(open, { keep = true } = {}) {
  if (keep) storage.write(railKey(), open);
  state.railOpen = open;
  $('#shell').dataset.rail = open ? 'open' : 'closed';
  bus.emit('rail-state', open);
}

/* "Skip to content" and the other skip links move the focus and nothing else: not the view, not the address. */
function skipTo(target) {
  if (target === 'main') { $('#main').focus(); return; }
  if (target === 'inspector') { $('#inspector').focus(); return; }
  if (PHONE.matches) {
    go('commands', { focus: true });
  } else {
    if (!state.railOpen) setRail(true, { keep: false });
    $('#rail').focus();
  }
}

export function initRouter() {
  window.addEventListener('hashchange', () => applyHash());
  document.addEventListener('click', inPlace);
  for (const link of $$('.skip')) {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      skipTo(link.getAttribute('href').slice(1));
    });
  }
  bus.on('go', (view) => (typeof view === 'string' ? go(view) : go(view.view, view)));
  bus.on('rail', (open) => setRail(open));
  PHONE.addEventListener('change', () => { if (state.view === 'commands' && !PHONE.matches) go('assistant'); });
  DOCKED.addEventListener('change', offerSkips);
  PHONE.addEventListener('change', offerSkips);
  setRail(railWanted(), { keep: false });
  applyHash(true);
}

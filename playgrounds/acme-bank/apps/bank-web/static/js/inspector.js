/* "Behind the answer": the hops of the one answer that is selected, one after the other. It is one place for the Assistant, Teams and Developers. A pinned head
   (which answer it is, in the sheet) and the hops, which are the only thing that scrolls. Docked beside the stage from 1280 px; below that it is a sheet that the
   answer's own control opens, and the sheet holds the same list.

   Every hop has the same four parts, whatever call it was: its title, three badges (the system the call went through, its status, how long it took), one line that
   says what happened, and the evidence of THAT call in Gamma (Trace and Logs; Decisions for a tool, Spend for a team); what the call held is behind a "Details". */
import { $, $$, h, bus, duration } from './dom.js';
import { icon } from './icons.js';
import { state, DOCKED, followNewest, selectTurn, subjectOf } from './store.js';
import { badge, clamped, empty, evidenceButtons, remeasure, say, summaryNode } from './ui.js';

const VIEWS = ['assistant', 'teams', 'developers'];
const TONES = ['ok', 'deny', 'block', 'limit', 'error'];
export const clock = (at) => new Date(at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

/* What the call held, behind one "Details" that is closed: the same on every hop that has something to show. */
function detailsNode(facts) {
  const shown = (Array.isArray(facts) ? facts : []).filter((fact) => fact && typeof fact.value === 'string' && fact.value);
  if (!shown.length) return null;
  const node = h('details', { class: 'hop-details' }, summaryNode(),
    h('dl', { class: 'facts' }, shown.flatMap((fact) => [h('dt', { text: fact.label }), h('dd', { class: fact.code ? 'code' : '' }, clamped(fact.value, fact.code ? 'fact json' : 'fact'))])));
  node.addEventListener('toggle', () => { if (node.open) remeasure(node); });
  return node;
}

/* The status badge says the number of the status; a call that has none says the word ("Error"). A call that went as it should is neutral, one that did not is loud
   and carries a mark. */
function statusBadge(row, tone) {
  const word = row.word || '';
  const refused = tone !== 'ok';
  return badge('status', row.status === null || row.status === undefined ? word : String(row.status), { tone: refused ? tone : null, word: row.status === null || row.status === undefined ? null : word, title: word });
}

/* One hop. The rail is a column of the row: a stem as tall as the row, and the dot on it. Rows touch, so the stems of two rows are one line whatever the rows hold. */
function hopNode(row) {
  const tone = TONES.includes(row.tone) ? row.tone : 'error';
  const time = duration(row.ms);
  return h('li', { class: `hop ${tone}`, 'data-kind': row.kind },
    h('div', { class: 'hop-rail', 'aria-hidden': 'true' }, h('span', { class: 'stem' }), h('span', { class: 'dot' })),
    h('div', { class: 'hop-main' },
      h('div', { class: 'hop-title', text: row.title }),
      h('div', { class: 'badges' },
        row.system ? badge(`system ${row.direct ? 'direct' : ''}`.trim(), row.system, { title: row.direct ? 'Nothing is in front of this call, so nothing was recorded' : row.system }) : null,
        statusBadge(row, tone),
        time ? badge('time', time) : null),
      h('p', { class: 'hop-summary', text: row.summary || '' }),
      evidenceButtons(row.evidence, row.title),
      detailsNode(row.facts)));
}

/* ---- the head and the hops of the selected answer --------------------------------------------------------------------- */

function skeleton() {
  return h('div', { class: 'behind-wait', 'aria-hidden': 'true' }, Array.from({ length: 4 }, () => h('div', { class: 'skeleton row' })));
}

let sheetView = null;           // the view whose answer the sheet shows
let drawn = null;               // what the inspector last drew: nothing is drawn again, nor the scroll and the focus lost, when nothing it shows changed

function renderInspector() {
  const view = sheetView || (VIEWS.includes(state.view) ? state.view : null);
  if (!view) return;
  const subject = subjectOf(view);
  const waiting = Boolean(state.working && view === 'assistant');
  if (drawn && drawn.view === view && drawn.subject === subject && drawn.waiting === waiting) return;
  drawn = { view, subject, waiting };
  const subjectLine = $('#behind-subject');
  const body = $('#behind-body');
  if (waiting) {
    subjectLine.textContent = '';
    body.replaceChildren(skeleton());
    $('#behind').setAttribute('aria-busy', 'true');
    return;
  }
  $('#behind').removeAttribute('aria-busy');
  if (!subject) {
    subjectLine.textContent = '';
    body.replaceChildren(empty(null, 'The call behind an answer shows here.'));
    $('#behind').classList.add('idle');
    return;
  }
  $('#behind').classList.remove('idle');
  subjectLine.textContent = subject.line;
  body.scrollTop = 0;
  body.replaceChildren(subject.rows.length ? h('ol', { class: 'timeline', 'aria-label': 'Hops' }, subject.rows.map(hopNode)) : null);
}

/* ---- the sheet: where the inspector is not beside the stage, the answer's own control opens it ---------------------------- */

let opener = null;
const FOREIGN = ['#topbar', '#rail', '#main', '#tabbar'];

const sheetOpen = () => $('#inspector').classList.contains('sheet');

/* The control under an answer where Behind the answer is not beside the stage (a sheet below 1280 px), named like what it opens. It is under the
   answer that is selected, and only there: one control, not one under each. */
export function behindButton(turn) {
  return h('button', { type: 'button', class: 'link-button hops-open', 'aria-label': 'Behind the answer',
    onclick: (event) => openSheet(turn, event.currentTarget) }, icon('activity', 'sm'), 'Behind the answer');
}

export function openSheet(turn, from) {
  const subject = state.turns.get(turn);
  if (!subject) return;
  sheetView = subject.view;                // the sheet shows this answer
  state.hold = subject.view;               // and a new answer that comes while it is read does not take its place
  selectTurn(turn);
  renderInspector();
  opener = from || document.activeElement;
  const sheet = $('#inspector');
  sheet.classList.add('sheet');
  sheet.setAttribute('role', 'dialog');
  sheet.setAttribute('aria-modal', 'true');
  sheet.setAttribute('aria-labelledby', 'behind-title');
  sheet.removeAttribute('aria-label');
  $('#scrim').hidden = false;
  $('#behind-close').hidden = false;
  for (const selector of FOREIGN) { const node = $(selector); if (node) node.setAttribute('inert', ''); }
  const title = $('#behind-title');
  title.tabIndex = -1;
  title.focus({ preventScroll: true });
  say(`Behind the answer, ${$('#behind-subject').textContent}`);
}

export function closeSheet({ back = true } = {}) {
  if (!sheetOpen()) return;
  const sheet = $('#inspector');
  sheet.classList.remove('sheet');
  sheet.removeAttribute('role');
  sheet.removeAttribute('aria-modal');
  sheet.removeAttribute('aria-labelledby');
  sheet.setAttribute('aria-label', 'Behind the answer');
  $('#scrim').hidden = true;
  $('#behind-close').hidden = true;
  for (const selector of FOREIGN) { const node = $(selector); if (node) node.removeAttribute('inert'); }
  const view = sheetView;
  sheetView = null;
  state.hold = null;
  if (view) followNewest(view);            // an answer that came while it was read takes its place now, unless the person chose the one they read
  if (back && opener && opener.isConnected) opener.focus({ preventScroll: true });
  opener = null;
}

/* Tab stays inside the sheet while it is open (everything else is inert; this keeps the sheet's own ring closed on itself). */
function trap(event) {
  if (event.key === 'Escape') { event.preventDefault(); closeSheet(); return; }
  if (event.key !== 'Tab') return;
  const stops = $$('a[href], button:not([disabled]), [tabindex="0"]', $('#inspector')).filter((node) => node.offsetParent !== null);
  if (!stops.length) return;
  const first = stops[0];
  const last = stops[stops.length - 1];
  if (event.shiftKey && (document.activeElement === first || document.activeElement === $('#behind-title'))) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}

export function initInspector() {
  $('#behind-close').addEventListener('click', () => closeSheet());
  $('#scrim').addEventListener('click', () => closeSheet());
  $('#inspector').addEventListener('keydown', (event) => { if (sheetOpen()) trap(event); });
  DOCKED.addEventListener('change', () => { if (DOCKED.matches) closeSheet({ back: false }); });
  bus.on('gamma-opened', () => closeSheet());        // handed over to Gamma from the sheet: the commands are not left under it
  for (const name of ['selected', 'view']) bus.on(name, renderInspector);
  renderInspector();
}

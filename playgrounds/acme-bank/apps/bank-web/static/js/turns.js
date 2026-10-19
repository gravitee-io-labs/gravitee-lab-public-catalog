/* What the turns of a conversation have in common, whoever made them (an answer of Ace, a payment): the box they are drawn in, the way an answer is
   selected (a click, and a real button for the keyboard), an answer that did not come. */
import { $, $$, h, reducedMotion } from './dom.js';
import { icon } from './icons.js';
import { state, selectTurn } from './store.js';
import { behindButton, clock } from './inspector.js';
import { hintNode, say } from './ui.js';

export const box = () => $('#conversation');

/* The end of a scroller, once what was just added is measured: a long answer is clamped and gets its "Show more" a frame later, so the end is lower by then,
   and an end taken at once would leave the bottom of the newest answer under the composer. */
export function toEnd(el, behavior = 'auto') {
  const go = () => el.scrollTo({ top: el.scrollHeight, behavior });
  go();
  requestAnimationFrame(() => requestAnimationFrame(go));
}

export function scrollDown() {
  toEnd(box(), reducedMotion() ? 'auto' : 'smooth');
}

/* The call on its way: a few dots where its answer will be, until it comes (Teams and Developers; the conversation has its own, with a way to stop). */
export const waitingNode = (iconName) => h('div', { class: 'msg ace', 'aria-busy': 'true' }, h('span', { class: 'tile sm' }, icon(iconName)),
  h('div', { class: 'bubble typing' }, h('div', { class: 'dots', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'))));

export function clearEmpty() {
  const el = $('[data-empty]', box());
  if (el) el.remove();
}

export function choose(id) {
  const turn = state.turns.get(id);
  if (selectTurn(id) && turn) say(`Showing the answer of ${clock(turn.at)}`);
}

/* The answer is selected by a click on it (not while somebody is selecting its words, and not on what is clickable inside it), and by this
   real button for the keyboard and a screen reader: one stop for the answer, which the click target stretches over. */
export const pickButton = (subject) => h('button', { type: 'button', class: 'pick sr', 'aria-pressed': 'false', onclick: () => choose(subject.id) },
  'Show what happened behind this answer');

export function clicked(event, id) {
  if (event.target.closest('a, button, summary, pre, .md-table, input')) return;
  if (window.getSelection && String(window.getSelection()).length) return;           // somebody is selecting words, not choosing an answer
  choose(id);
}

/* The selected turn of a view carries a mark (a conversation, or the feed of Teams or Developers). */
export function markSelected(view = 'assistant', root = box()) {
  const chosen = state.selected[view];
  for (const node of $$('[data-turn]', root)) {
    const on = node.dataset.turn === chosen;
    node.classList.toggle('sel', on);
    const pick = node.querySelector('.pick');
    if (pick) pick.setAttribute('aria-pressed', String(on));
  }
}

/* Who is asking, by first name: what the title of a hop calls the person, and nobody in the words of the server's hops (hops.py, `NOBODY`). */
export const firstName = () => (state.persona ? state.persona.name.split(' ')[0] : 'Someone not signed in');

/* The call that did not come back, as Behind the answer shows it: the hop the gateway answered with, when the app has it (the server sends it with the
   failure), else one hop of the app's own, with the status the app got (none when the app itself did not answer). */
export function failedSubject(id, n, response, { text, started, title, message }) {
  const now = Date.now();
  const sent = Array.isArray(response.data && response.data.rows) ? response.data.rows : [];
  const own = { kind: 'error', name: '', title, system: null, direct: false, outcome: 'error', tone: 'error', word: 'Error', status: response.status || null, ms: now - started,
    summary: `Error: ${message}`, facts: [], evidence: [] };
  return { id, view: 'assistant', kind: 'failed', n, at: now, ms: now - started, gateway: true, line: `${clock(now)} · ${text}`, rows: sent.length ? sent : [own] };
}

/* An answer that did not come: said once, as an alert, in the conversation, and selectable like any answer. */
export function problem(text, actions, hint, subject) {
  return h('article', { class: 'msg problem', 'data-turn': subject.id, onclick: (event) => clicked(event, subject.id) },
    h('span', { class: 'tile sm', 'aria-hidden': 'true' }, icon('alert')),
    h('div', { class: 'reply' }, h('div', { class: 'bubble', role: 'alert' }, text), hintNode(hint),
      h('div', { class: 'meta' }, behindButton(subject.id)),
      actions.length ? h('div', { class: 'problem-actions' }, actions) : null, pickButton(subject)));
}

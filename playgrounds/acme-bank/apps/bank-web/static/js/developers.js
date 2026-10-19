/* Developers: the LLM proxy, called with the Developers key (the key stays on the server). Same frame as the others: the answers come one after
   the other, the tokens left this minute are the monitor, and the answer that is selected has its call Behind it. */
import { $, h, api, bus, count } from './dom.js';
import { icon } from './icons.js';
import { failure } from './errors.js';
import { addTurn } from './store.js';
import { behindButton } from './inspector.js';
import { clicked, markSelected, pickButton, toEnd, waitingNode } from './turns.js';
import { clamped, empty, hintNode, say, whileBusy } from './ui.js';

const TIMEOUT = 120 * 1000;
let answers = 0;
let limits = null;
let faq = Math.floor(Math.random() * 1000);       // the next FAQ to ask: the server takes it modulo its list

const feed = () => $('#dev-feed');

/* The tokens the key may still use this minute, said once, with the meter and when it resets. */
function renderLimit() {
  const box = $('#dev-limit');
  if (!limits || limits.limit === null || limits.remaining === null) {
    box.replaceChildren(h('div', { class: 'budget-top' }, h('span', { class: 'budget-figure' }, h('span', { class: 'none', text: '—' }), ' ', h('small', { text: 'no call yet' }))),
      h('div', { class: 'meter', 'aria-hidden': 'true' }, h('i')));
    return;
  }
  const percent = Math.round((100 * limits.remaining) / limits.limit);
  const seconds = limits.reset ? Math.max(0, Math.round((limits.reset - Date.now()) / 1000)) : null;
  const meter = h('div', { class: `meter ${percent === 0 ? 'empty' : percent <= 25 ? 'low' : ''}`.trim(), role: 'meter', 'aria-label': 'Model tokens left this minute',
    'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(percent), 'aria-valuetext': `${count(limits.remaining)} of ${count(limits.limit)} tokens left` }, h('i'));
  meter.firstChild.style.setProperty('--w', percent);
  box.replaceChildren(
    h('div', { class: 'budget-top' }, h('span', { class: 'budget-figure' }, count(limits.remaining), ' ', h('small', { text: `left of ${count(limits.limit)}` }))),
    meter,
    seconds !== null ? h('div', { class: 'budget-foot' }, h('span', { text: seconds ? 'Resets in ' : 'Resets ' }), h('b', { text: seconds ? `${seconds} s` : 'now' })) : null);
}

function addAnswer(result, question, { asked = null } = {}) {
  answers += 1;
  const box = feed();
  const first = box.firstElementChild;
  if (first && first.classList.contains('empty')) first.remove();
  const text = result.status === 200 ? result.answer : result.message;
  const subject = { id: `d${answers}`, view: 'developers', kind: 'dev', n: answers, at: Date.now(), ms: result.ms, gateway: true,
    line: `#${answers} · ${String(question).replace(/\s+/g, ' ').slice(0, 120)}`, rows: result.rows };
  addTurn(subject);
  box.append(h('article', { class: 'answer', 'data-turn': subject.id, onclick: (event) => clicked(event, subject.id) },
    h('div', { class: 'answer-top' }, h('strong', { class: 'num', text: `#${answers}` }),
      behindButton(subject.id)),
    asked ? h('p', { class: 'answer-ask', title: asked, text: asked }) : null,
    clamped(text, result.status === 200 ? '' : 'muted'), pickButton(subject)));
  markSelected('developers', box);
  toEnd(box);
  if (result.limits) { limits = result.limits; renderLimit(); }
  say(`Answer ${answers}: ${String(text || '').replace(/\s+/g, ' ').slice(0, 200)}`);
}

/* The call on its way: a few dots at the end of the feed, as in the others, until the answer comes. */
async function call(body) {
  const box = feed();
  if (box.firstElementChild && box.firstElementChild.classList.contains('empty')) box.firstElementChild.remove();
  const wait = waitingNode('code');
  box.append(wait);
  toEnd(box);
  const response = await api('/api/dev/llm', { method: 'POST', body, timeout: TIMEOUT });
  wait.remove();
  if (!response.ok) {
    const { text, hint } = failure(response);
    box.append(h('div', { class: 'msg problem' }, h('span', { class: 'tile sm', 'aria-hidden': 'true' }, icon('alert')),
      h('div', { class: 'reply' }, h('div', { class: 'bubble', role: 'alert' }, text), hintNode(hint))));
    toEnd(box);
    return null;
  }
  /* What was asked is under the number of its answer: the cached FAQ is a question the server picks, and it says which. A burst asks one question ten times. */
  addAnswer(response.data, body.faq !== undefined ? 'The cached FAQ' : body.message, { asked: body.variation === undefined ? response.data.question || null : null });
  return response.data;
}

export function initDevelopers() {
  const buttons = ['#dev-send', '#dev-burst', '#dev-faq'].map((s) => $(s));
  const message = () => $('#dev-message').value;
  $('#dev-form').addEventListener('submit', (event) => {
    event.preventDefault();
    if (!message().trim()) { $('#dev-message').focus(); return; }
    whileBusy(buttons, () => call({ message: message() }));
  });
  $('#dev-burst').addEventListener('click', () => whileBusy(buttons, async () => {
    const label = $('#dev-burst span:last-child');
    for (let n = 1; n <= 10; n += 1) {
      label.textContent = `Sending ${n} of 10`;
      const result = await call({ message: message(), variation: n });
      if (!result || result.status !== 200) break;       // the first 429 says it all
    }
    label.textContent = 'Send x10';
  }));
  $('#dev-faq').addEventListener('click', () => whileBusy(buttons, async () => {
    const which = faq;
    faq += 1;
    for (let n = 0; n < 2; n += 1) if (!await call({ faq: which })) break;
  }));
  feed().replaceChildren(empty('code', 'No answer yet. Send a question.'));
  renderLimit();
  bus.on('selected', (view) => { if (view === 'developers') markSelected('developers', feed()); });
  setInterval(() => { if (!$('#view-developers').hidden && limits && limits.reset) renderLimit(); }, 1000);
}

/* Handed over to Gamma from Behind the answer. Framed by the Lab UI, a way into Gamma (Trace, Logs, Decisions, Spend, Open in Gamma, Open Gamma) posts its address
   to the Lab UI, which shows it in its own tab: the sheet of Behind the answer, which covers the lessons, closes with it, so that the person comes back to the
   lessons. Standalone a browser tab opens and the page stays as it is. Run for real over a small DOM: the click, the message, the sheet. */
import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

import { Ev, flush, installDom, text } from './dom-stub.mjs';

const page = installDom({ ids: ['topbar', 'rail', 'main', 'tabbar', 'inspector', 'behind', 'behind-title', 'behind-close', 'behind-subject', 'behind-body', 'scrim', 'announcer', 'toasts'],
  media: { '(min-width: 1280px)': false }, fetch: async (path) => fetched(path) });
mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: 1_000_000 });
page.ids.scrim.hidden = true;
page.ids['behind-close'].tag = 'button';
page.ids['behind-close'].hidden = true;
page.ids.behind.append(page.ids['behind-title'], page.ids['behind-close'], page.ids['behind-subject'], page.ids['behind-body']);
page.ids.inspector.append(page.ids.behind);
const store = await import('../../static/js/store.js');
const { bus, h } = await import('../../static/js/dom.js');
const inspector = await import('../../static/js/inspector.js');
const { initEmbed } = await import('../../static/js/embed.js');
const { state } = store;

let fetched = async () => ({ ok: true, status: 200, json: async () => ({ state: 'found', url: 'http://gamma.test/environments/default/aim/observe/tracing/api-1/trace-9' }) });
const posted = [];
const lab = { postMessage: (message, origin) => posted.push({ message, origin }) };
const framed = () => { globalThis.window.parent = lab; };
const standalone = () => { globalThis.window.parent = globalThis.window; };
framed();
inspector.initInspector();
initEmbed();

const link = (kind, url) => ({ kind, label: { trace: 'Trace', logs: 'Logs', decisions: 'Decisions', spend: 'Spend' }[kind], url });
const EVIDENCE = [link('trace', '/api/evidence?kind=trace&api=a2a&request=req-12345678&at=1'), link('logs', 'http://gamma.test/environments/default/aim/observe/logs'),
  link('decisions', 'http://gamma.test/environments/default/authz/observe/logs'), link('spend', 'http://gamma.test/environments/default/aim/ai-workspaces/ws-1/spend')];
const opener = h('button', { type: 'button', 'data-key': 'hops' }, 'Behind the answer');
page.ids.rail.append(opener);
let n = 0;
function answer() {
  n += 1;
  const subject = { id: `t${n}`, view: 'assistant', kind: 'chat', n, at: 1_000_000, ms: 100, gateway: true, line: '10:28 · Show my accounts',
    rows: [{ kind: 'tool', name: 'get_balance', outcome: 'ok', title: 'Ace called get_balance', system: 'MCP proxy', direct: false, tone: 'ok', word: 'Answered', summary: 'The bank\'s tool answered.', facts: [],
      status: 200, ms: 374, evidence: EVIDENCE }] };
  store.addTurn(subject);
  return subject;
}
function reset() {
  posted.length = 0;
  state.turns.clear();
  state.selected = { assistant: null, teams: null, developers: null };
  state.pinned = { assistant: false, teams: false, developers: false };
  state.view = 'assistant';
  state.hold = null;
  inspector.closeSheet({ back: false });
  page.ids.toasts.replaceChildren();
  framed();
}
const open = () => page.ids.inspector.classList.contains('sheet');
const evidence = (label) => page.ids['behind-body'].querySelectorAll('.evidence').find((a) => text(a) === label);
const click = (a) => { const event = new Ev('click', { target: a }); page.doc.dispatchEvent(event); return event; };
const sheet = () => { reset(); inspector.openSheet(answer().id, opener); assert.equal(open(), true); };
const closed = () => {
  assert.equal(open(), false, 'the sheet is closed');
  assert.equal(page.ids.scrim.hidden, true, 'its scrim is gone');
  assert.equal(page.ids['behind-close'].hidden, true);
  for (const id of ['topbar', 'rail', 'main', 'tabbar']) assert.equal(page.ids[id].hasAttribute('inert'), false, `${id} is not inert: the page can be used`);
  assert.equal(state.hold, null);
};

test('from the sheet, every way into Gamma that Behind the answer offers hands over to the Lab UI and closes the sheet', async () => {
  for (const kind of ['Trace', 'Logs', 'Decisions', 'Spend']) {
    sheet();
    assert.equal(page.ids['behind-body'].querySelectorAll('.evidence').length, 4, 'the sheet holds the buttons of the hop');
    const event = click(evidence(kind));
    await flush();
    assert.equal(event.defaultPrevented, true, `${kind}: no browser tab opens`);
    assert.equal(posted.length > 0 && posted.every((one) => one.message.type === 'gravitee-lab:open'), true, `${kind}: the Lab UI was asked to show it`);
    closed();
    assert.equal(page.focused(), opener, `${kind}: the focus is back on the control that opened it, for the person who comes back`);
  }
});

test('the Trace is looked up first: the sheet is closed when the address is posted, not before, and a trace that is not found closes nothing', async () => {
  sheet();
  let answered;
  fetched = () => new Promise((resolve) => { answered = resolve; });
  click(evidence('Trace'));
  await flush();
  assert.equal(open(), true, 'the lookup is not over: the person is still here');
  assert.deepEqual(posted, []);
  answered({ ok: true, status: 200, json: async () => ({ state: 'found', url: 'http://gamma.test/environments/default/aim/observe/tracing/api-1/trace-9' }) });
  await flush();
  assert.equal(posted.length > 0, true);
  closed();
  // not found: nothing was handed over, so the sheet stays, and the person is told
  sheet();
  fetched = async () => ({ ok: false, status: 404, json: async () => ({ error: 'no trace' }) });
  click(evidence('Trace'));
  await flush();
  assert.deepEqual(posted, []);
  assert.equal(open(), true, 'the sheet is where the person can try again');
  assert.match(text(page.ids.toasts), /Can't open this in Gamma yet/);
  fetched = async () => ({ ok: true, status: 200, json: async () => ({ state: 'found', url: 'http://gamma.test/x' }) });
});

test('Open Gamma of the header is a way into Gamma too: it hands over and leaves nothing open', async () => {
  for (const [name, attrs] of [['Open Gamma', { class: 'btn btn-platform', href: 'http://gamma.test/' }]]) {
    sheet();
    const a = h('a', { target: '_blank', rel: 'noopener', 'data-gamma': '', ...attrs }, name);
    page.body.append(a);
    click(a);
    await flush();
    assert.equal(posted.length > 0, true, name);
    closed();
    a.remove();
  }
});

test('standalone a browser tab opens and the page stays as it is: the sheet is still there', async () => {
  sheet();
  standalone();
  for (const kind of ['Trace', 'Logs', 'Decisions', 'Spend']) {
    const event = click(evidence(kind));
    await flush();
    assert.equal(event.defaultPrevented, false, `${kind}: the link opens its tab`);
  }
  assert.deepEqual(posted, [], 'nobody is told');
  assert.equal(open(), true, 'and the sheet stays open');
  assert.equal(page.ids.scrim.hidden, false);
  assert.equal(page.ids.rail.hasAttribute('inert'), true);
  framed();
});

test('where Behind the answer is beside the stage there is no sheet: the hand over leaves the column as it was', async () => {
  reset();
  page.setMedia('(min-width: 1280px)', true);
  answer();
  assert.equal(open(), false);
  const event = click(evidence('Logs'));
  await flush();
  assert.equal(event.defaultPrevented, true);
  assert.equal(posted.length > 0, true);
  assert.equal(open(), false);
  assert.equal(page.ids['behind-body'].querySelectorAll('.evidence').length, 4, 'the column still holds its evidence');
  page.setMedia('(min-width: 1280px)', false);
});

test('a link that is not a way into Gamma hands nothing over, and the sheet stays', async () => {
  sheet();
  const other = h('a', { href: 'https://evil.example/login', target: '_blank', rel: 'noopener' }, 'x');
  page.body.append(other);
  click(other);
  await flush();
  assert.deepEqual(posted, []);
  assert.equal(open(), true);
  other.remove();
  inspector.closeSheet({ back: false });
});

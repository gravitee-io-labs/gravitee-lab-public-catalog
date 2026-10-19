/* Behind the answer over a small DOM: which answer it shows; the hops, each in the same four parts (a title, three badges, one line, the evidence of its own call)
   and what it held behind one "Details"; the rail made of the rows; a direct call; the skeleton of a call that takes long; and the sheet it becomes where it is not
   beside the stage (a dialog: it takes the focus, Tab stays inside it, Escape closes it and the focus goes back). */
import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

import { Ev, installDom, text } from './dom-stub.mjs';

const page = installDom({ ids: ['topbar', 'rail', 'main', 'tabbar', 'inspector', 'behind', 'behind-title', 'behind-close', 'behind-subject', 'behind-body', 'scrim', 'announcer'],
  media: { '(min-width: 1280px)': true } });
mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: 1_000_000 });
page.ids.scrim.hidden = true;
page.ids['behind-close'].tag = 'button';
page.ids['behind-close'].hidden = true;
page.ids.behind.append(page.ids['behind-title'], page.ids['behind-close'], page.ids['behind-subject'], page.ids['behind-body']);
page.ids.inspector.append(page.ids.behind);
const store = await import('../../static/js/store.js');
const { bus } = await import('../../static/js/dom.js');
const inspector = await import('../../static/js/inspector.js');
const { state } = store;
inspector.initInspector();

const WORDS = { ok: 'Answered', deny: 'Denied by policy', block: 'Blocked', limit: 'Limited', error: 'Error' };
const link = (kind, extra = {}) => ({ kind, label: { trace: 'Trace', logs: 'Logs', decisions: 'Decisions', spend: 'Spend' }[kind], url: `http://gamma.test/${kind}`, ...extra });
const hop = (extra = {}) => ({ kind: 'llm', name: 'acme-chat', title: 'Ace asked the model what to do', system: 'LLM proxy', direct: false, outcome: 'ok', tone: 'ok', word: 'Answered', status: 200, ms: 374,
  summary: 'The model chose list_accounts.', facts: [], evidence: [], ...extra });
const refused = (extra = {}) => hop({ kind: 'tool', title: 'Ace called list_accounts', system: 'MCP proxy', outcome: 'denied', tone: 'deny', word: WORDS.deny, status: 403, ms: 9,
  summary: 'Denied by policy: Not allowed by ACME policy', ...extra });
let n = 0;
function turn(extra = {}) {
  n += 1;
  return { id: `t${n}`, view: 'assistant', kind: 'chat', n, at: 1_000_000, ms: 100, gateway: true, line: '10:28 · Show my accounts', rows: [hop()], ...extra };
}
function reset() {
  state.turns.clear();
  state.selected = { assistant: null, teams: null, developers: null };
  state.pinned = { assistant: false, teams: false, developers: false };
  state.working = false;
  state.view = 'assistant';
  state.hold = null;
  inspector.closeSheet({ back: false });
}
const hops = () => page.ids['behind-body'].querySelectorAll('.hop');
const labels = (node) => node.querySelectorAll('.evidence').map((a) => text(a));

test('before any answer the head is the title and nothing else, and the column says in one line what to do: no marks that look as if something were loading', () => {
  reset();
  bus.emit('selected', 'assistant');
  assert.equal(page.ids.behind.classList.contains('idle'), true);
  assert.equal(page.ids['behind-subject'].textContent, '');
  assert.equal(text(page.ids['behind-body']), 'The call behind an answer shows here.');
  assert.equal(page.ids['behind-body'].querySelectorAll('svg, .skeleton, .spinner').length, 0, 'a sentence, not a picture of something on its way');
  assert.equal(page.ids['behind-body'].querySelectorAll('.timeline, .hop').length, 0);
});

test('the one line is there in every view that has the inspector, and goes when an answer is selected', () => {
  reset();
  for (const view of ['assistant', 'teams', 'developers']) {
    store.state.view = view;
    bus.emit('view', view);
    assert.equal(text(page.ids['behind-body']), 'The call behind an answer shows here.', view);
  }
  store.state.view = 'assistant';
  store.addTurn(turn({ rows: [hop({})] }));
  bus.emit('selected', 'assistant');
  assert.doesNotMatch(text(page.ids['behind-body']), /The call behind an answer shows here/);
});

test('every hop is the same four parts in the same order, whatever call it was: a title, badges, one line, then the evidence and the details where it has any', () => {
  reset();
  store.addTurn(turn({ rows: [
    hop({ kind: 'a2a', title: 'Alice asked Ace', system: 'A2A proxy', summary: 'Ace received the question and answered.', evidence: [link('trace'), link('logs')] }),
    hop({ kind: 'exchange', title: 'Ace got a token for Alice', system: 'Access Management', summary: 'sub Alice, acting agent ace-agent', ms: 12 }),
    hop({ facts: [{ label: 'Model', value: 'acme-chat', code: false }], evidence: [link('trace'), link('logs')] }),
    refused({ facts: [{ label: 'Asked', value: 'customer_id C-1001', code: true }], evidence: [link('trace'), link('logs'), link('decisions')] }),
  ] }));
  const found = hops();
  assert.equal(found.length, 4);
  for (const one of found) {
    const parts = one.querySelector('.hop-main').children.map((child) => child.getAttribute('class').split(' ')[0]);
    assert.deepEqual(parts.slice(0, 3), ['hop-title', 'badges', 'hop-summary'], 'the same first three parts on every hop');
    assert.deepEqual(parts.slice(3).filter((part) => !['hop-evidence', 'hop-details'].includes(part)), [], 'and nothing else but the evidence and the details, in that order');
    if (parts.length === 5) assert.deepEqual(parts.slice(3), ['hop-evidence', 'hop-details']);
    assert.equal(one.querySelectorAll('.badge').length >= 2, true, 'a system, a status and a time');
  }
  assert.equal(text(found[0].querySelector('.hop-title')), 'Alice asked Ace');
  assert.equal(text(found[0].querySelector('.hop-summary')), 'Ace received the question and answered.');
  assert.deepEqual(found.map((one) => one.querySelectorAll('.hop-evidence').length), [1, 0, 1, 1], 'the token exchange is not behind the gateway: it has no evidence to offer');
  assert.deepEqual(found.map((one) => one.querySelectorAll('details').length), [0, 0, 1, 1], 'a hop with nothing to show has no Details');
});

test('the three badges are the system the call went through, its status and its time, in that order, and the time is a figure', () => {
  reset();
  store.addTurn(turn({ rows: [hop({ ms: 374 }), hop({ ms: 2100, system: 'A2A proxy' }), hop({ ms: null, status: 200 })] }));
  const [first, second, third] = hops().map((one) => one.querySelector('.badges').querySelectorAll('.badge'));
  assert.deepEqual(first.map((b) => text(b)), ['LLM proxy', '200 Answered', '374 ms']);
  assert.deepEqual(first.map((b) => b.getAttribute('class')), ['badge system', 'badge status', 'badge time']);
  assert.deepEqual(second.map((b) => text(b)), ['A2A proxy', '200 Answered', '2.1 s']);
  assert.deepEqual(third.map((b) => text(b)), ['LLM proxy', '200 Answered'], 'a call that does not say how long it took has no time badge');
});

test('a hop that went as it should is neutral and says Answered to a screen reader; one that did not is loud, with a mark, a word and its tone', () => {
  reset();
  store.addTurn(turn({ rows: [hop(), refused(), hop({ tone: 'block', word: 'Blocked', status: 400 }), hop({ tone: 'limit', word: 'Limited', status: 429 }), hop({ tone: 'error', word: 'Error', status: 504 })] }));
  const [ok, ...bad] = hops();
  const status = (one) => one.querySelector('.badge.status');
  assert.equal(status(ok).getAttribute('class'), 'badge status');
  assert.equal(status(ok).querySelectorAll('svg').length, 0);
  assert.equal(text(status(ok).querySelector('.sr')), 'Answered');
  assert.deepEqual(bad.map((one) => status(one).getAttribute('class')), ['badge status deny', 'badge status block', 'badge status limit', 'badge status error']);
  assert.deepEqual(bad.map((one) => text(status(one).querySelector('.sr'))), ['Denied by policy', 'Blocked', 'Limited', 'Error']);
  assert.deepEqual(bad.map((one) => status(one).querySelectorAll('svg').length), [1, 1, 1, 1], 'a mark beside the number: the color is not what says it');
  assert.deepEqual(bad.map((one) => status(one).getAttribute('title')), ['Denied by policy', 'Blocked', 'Limited', 'Error']);
  assert.deepEqual(hops().map((one) => one.getAttribute('class')), ['hop ok', 'hop deny', 'hop block', 'hop limit', 'hop error']);
  assert.equal(text(bad[0].querySelector('.hop-summary')), 'Denied by policy: Not allowed by ACME policy', 'the reason, in the one line of the hop');
});

test('a call that has no status says the word instead of a number, and a tone the page does not know is an error', () => {
  reset();
  store.addTurn(turn({ rows: [hop({ tone: 'error', word: 'Error', status: null, summary: 'Error: Ace could not finish.' }), hop({ tone: 'surprise', word: 'Something', status: 200 })] }));
  const [none, odd] = hops();
  assert.equal(text(none.querySelector('.badge.status')), 'Error');
  assert.equal(none.querySelector('.badge.status').querySelectorAll('.sr').length, 0, 'the word is not said twice');
  assert.equal(odd.getAttribute('class'), 'hop error', 'loud rather than quiet');
});

test('a token Ace kept from an earlier question says so in the place of a status and a time: Access Management was not asked, so no 200 and no duration are shown', () => {
  reset();
  store.addTurn(turn({ rows: [hop({ kind: 'exchange', title: 'Ace got a token for Alice', system: 'Access Management', word: 'Reused', status: null, ms: null,
    summary: 'Ace used the token it got earlier: sub Alice, acting agent ace-agent.' }),
  hop({ kind: 'exchange', title: 'Ace got a token for Alice', system: 'Access Management', status: 200, ms: 24, summary: 'Access Management issued it: sub Alice, acting agent ace-agent.' })] }));
  const [reused, issued] = hops();
  assert.deepEqual(reused.querySelectorAll('.badge').map((b) => text(b)), ['Access Management', 'Reused']);
  assert.deepEqual(issued.querySelectorAll('.badge').map((b) => text(b)), ['Access Management', '200 Answered', '24 ms']);
});

test('the system badge, which may be cut at the narrowest width, says its name in full; the status and the time are never cut', () => {
  reset();
  store.addTurn(turn({ rows: [hop({ system: 'Access Management' })] }));
  const [system, status, time] = hops()[0].querySelectorAll('.badge');
  assert.equal(system.getAttribute('title'), 'Access Management');
  assert.equal(system.querySelectorAll('span').length, 1, 'one text, which the stylesheet gives the ellipsis to');
  assert.equal(status.hasAttribute('title'), true);
  assert.equal(time.hasAttribute('title'), false);
});

test('the buttons of a hop are those of its own call, side by side in one fixed order, and a hop that has none shows no row', () => {
  reset();
  store.addTurn(turn({ rows: [hop({ evidence: [link('logs'), link('decisions'), link('trace')] }), hop({ evidence: [link('spend'), link('logs')] }), hop({ evidence: [] }),
    hop({ evidence: [{ kind: 'logs', label: 'Logs', url: 'javascript:alert(1)' }] })] }));
  const [one, two, three, four] = hops();
  assert.deepEqual(labels(one), ['Trace', 'Logs', 'Decisions']);
  assert.deepEqual(labels(two), ['Logs', 'Spend']);
  assert.equal(three.querySelectorAll('.hop-evidence').length, 0);
  assert.equal(four.querySelectorAll('.hop-evidence').length, 0, 'a link that is not Gamma\'s is not drawn, and with none there is no row');
  const [trace] = one.querySelectorAll('.evidence');
  assert.equal(trace.hasAttribute('data-gamma'), true, 'in the Lab UI it opens its tab of Gamma');
  assert.equal(trace.getAttribute('target'), '_blank');
  assert.equal(one.querySelectorAll('.hop-evidence')[0].getAttribute('aria-label'), 'Evidence in Gamma, Ace asked the model what to do');
  assert.equal(page.ids['behind-subject'].querySelectorAll('.evidence').length, 0, 'none at the head of the inspector: the first hop is the answer\'s own call');
});

test('what a call held is behind one Details on every hop that has something, closed, and nothing of it is shown outside it', () => {
  reset();
  store.addTurn(turn({ rows: [
    hop({ facts: [{ label: 'Model', value: 'acme-chat', code: false }, { label: 'Tokens', value: '1,161', code: false }] }),
    refused({ facts: [{ label: 'Asked', value: 'customer_id C-1001', code: true }] }),
    hop({ kind: 'tool', title: 'Ace called get_balance', facts: [{ label: 'Asked', value: 'account_id ACC-1001', code: true }, { label: 'Result', value: '{"balance": 4820.55}', code: true }] }),
  ] }));
  for (const one of hops()) {
    const details = one.querySelectorAll('details');
    assert.equal(details.length, 1);
    assert.equal(details[0].open, false, 'closed by default');
    assert.equal(text(details[0].querySelector('summary')), 'Details', 'the same word on every hop');
    assert.equal(details[0].querySelectorAll('summary svg').length, 1, 'and the same chevron, which turns when it is open (the page\'s icons, not the browser\'s triangle)');
    assert.equal(one.querySelectorAll('.facts').length, 1);
    assert.equal(details[0].contains(one.querySelector('.facts')), true, 'what it held is inside it');
    assert.equal(one.querySelectorAll('.clamp').length, one.querySelectorAll('details .clamp').length, 'no raw content outside it');
  }
  const [model, , tool] = hops();
  assert.deepEqual(model.querySelectorAll('dt').map((dt) => text(dt)), ['Model', 'Tokens']);
  assert.deepEqual(tool.querySelectorAll('dt').map((dt) => text(dt)), ['Asked', 'Result']);
  assert.equal(tool.querySelectorAll('dd')[1].querySelector('.clamp').classList.contains('json'), true, 'what a tool asked and said is read in the type of code');
  assert.equal(model.querySelectorAll('dd')[0].querySelector('.clamp').classList.contains('json'), false, 'and what a model is called is not');
  assert.equal(text(page.ids['behind-body']).includes('customer_id') && !page.ids['behind-body'].querySelector('.hop-summary').textContent.includes('customer_id'), true);
});

test('a long text inside a closed Details is measured when it opens, and offers Show more only if it is long', () => {
  reset();
  store.addTurn(turn({ rows: [hop({ kind: 'tool', facts: [{ label: 'Result', value: 'x '.repeat(400), code: true }, { label: 'Asked', value: 'a', code: true }] })] }));
  const [one] = hops();
  const details = one.querySelector('details');
  const [long, short] = details.querySelectorAll('.clamp');
  mock.timers.tick(10);                                              // closed, a browser measures nothing: both are 0 high
  const [moreLong, moreShort] = details.querySelectorAll('button');
  assert.equal(moreLong.hidden, true, 'closed: nothing could be measured');
  Object.defineProperty(long, 'scrollHeight', { value: 200 });      // opened, the long one is taller than its three lines
  Object.defineProperty(long, 'clientHeight', { value: 60 });
  details.open = true;
  details.dispatchEvent(new Ev('toggle'));
  mock.timers.tick(10);
  assert.equal(moreLong.hidden, false, 'opened: it is long, and there is more to read');
  assert.equal(long.classList.contains('fades'), true);
  assert.equal(moreShort.hidden, true, 'a short one has none');
  assert.equal(short.classList.contains('fades'), false);
  moreLong.click();
  assert.equal(text(moreLong), 'Show less');
  details.dispatchEvent(new Ev('toggle'));
  mock.timers.tick(10);
  assert.equal(moreLong.hidden, false, 'opened and read in full: the way back is still there');
});

test('the rail is made of the rows: every hop has a stem and a dot, hidden from a screen reader, whatever the hop is', () => {
  reset();
  store.addTurn(turn({ rows: [hop(), refused(), hop({ tone: 'block', word: 'Blocked' }), hop({ tone: 'limit', word: 'Limited' }), hop({ tone: 'error', word: 'Error', status: null }), hop({ system: 'No gateway', direct: true })] }));
  for (const one of hops()) {
    const [rail, ...rest] = one.children;
    assert.equal(rail.getAttribute('class'), 'hop-rail');
    assert.equal(rail.getAttribute('aria-hidden'), 'true');
    assert.deepEqual(rail.children.map((c) => c.getAttribute('class')), ['stem', 'dot'], 'the same two pieces on every row');
    assert.deepEqual(rest.map((c) => c.getAttribute('class')), ['hop-main']);
  }
  assert.equal(page.ids['behind-body'].querySelector('ol').getAttribute('aria-label'), 'Hops');
  assert.equal(page.ids['behind-body'].querySelectorAll('li').length, 6, 'one list item for each hop: the order is the list\'s');
});

test('a call that went direct says so in its badge, in place of a system, and has no evidence to offer; the hops are drawn as the others', () => {
  reset();
  store.addTurn(turn({ gateway: false, rows: [hop({ kind: 'a2a', title: 'Alice asked Ace', system: 'No gateway', direct: true, summary: 'Ace received the question and answered.' }),
    hop({ title: 'Ace called get_balance', system: 'No gateway', direct: true })] }));
  const [first, second] = hops();
  const system = first.querySelector('.badge.system');
  assert.equal(text(system), 'No gateway');
  assert.equal(system.getAttribute('class'), 'badge system direct');
  assert.equal(system.getAttribute('title'), 'Nothing is in front of this call, so nothing was recorded');
  assert.equal(second.querySelector('.badge.system').getAttribute('class'), 'badge system direct');
  assert.equal(page.ids['behind-body'].querySelectorAll('.evidence').length, 0);
  store.addTurn(turn({ rows: [hop({ system: 'LLM proxy' })] }));
  assert.equal(page.ids['behind-body'].querySelector('.badge.system').getAttribute('class'), 'badge system');
  assert.equal(page.ids['behind-body'].querySelector('.badge.system').getAttribute('title'), 'LLM proxy', 'a name that may be cut says itself in full');
});

test('a hop that names no system draws no system badge, and a turn with no hop draws no list', () => {
  reset();
  store.addTurn(turn({ rows: [hop({ system: null })] }));
  assert.deepEqual(hops()[0].querySelectorAll('.badge').map((b) => text(b)), ['200 Answered', '374 ms']);
  store.addTurn(turn({ rows: [] }));
  assert.equal(page.ids['behind-body'].querySelectorAll('ol').length, 0);
});

test('a call that takes long shows a skeleton in place of the hops, and the hops come back when it is over', () => {
  reset();
  store.addTurn(turn());
  state.working = true;
  bus.emit('selected', 'assistant');
  assert.equal(page.ids['behind-body'].querySelectorAll('.skeleton').length > 0, true);
  assert.equal(page.ids.behind.getAttribute('aria-busy'), 'true');
  assert.equal(page.ids['behind-subject'].textContent, '');
  state.working = false;
  bus.emit('selected', 'assistant');
  assert.equal(page.ids['behind-body'].querySelectorAll('.hop').length, 1);
  assert.equal(page.ids.behind.getAttribute('aria-busy'), null);
});

test('the newest answer is selected unless the person chose an older one, and the answer to a command always is', () => {
  reset();
  const first = turn({ line: 'first' });
  store.addTurn(first);
  assert.equal(state.selected.assistant, first.id);
  const second = turn({ line: 'second' });
  store.addTurn(second);
  assert.equal(state.selected.assistant, second.id, 'a new answer is the one to look at');
  assert.equal(store.selectTurn(first.id), true);
  assert.equal(page.ids['behind-subject'].textContent, 'first');
  const third = turn({ line: 'third' });
  store.addTurn(third);
  assert.equal(state.selected.assistant, first.id, 'the person chose the older one: it stays');
  const fourth = turn({ line: 'fourth' });
  store.addTurn(fourth, { select: true });
  assert.equal(state.selected.assistant, fourth.id, 'a command always selects its answer');
  assert.equal(state.pinned.assistant, false);
  store.selectTurn(fourth.id);
  store.addTurn(turn());
  assert.notEqual(state.selected.assistant, fourth.id, 'choosing the newest follows the conversation again');
});

test('forgetting the turns of a view clears the selection', () => {
  reset();
  const first = turn();
  store.addTurn(first);
  store.forgetTurns('assistant');
  assert.equal(state.selected.assistant, null);
  assert.equal(page.ids['behind-body'].querySelectorAll('.hop').length, 0);
});

test('where the inspector is not beside the stage a control opens it as a dialog: the focus goes to its title, everything else is inert, and the scrim shows', () => {
  reset();
  const asked = turn({ rows: [hop({ evidence: [link('trace')] })] });
  store.addTurn(asked);
  const opener = page.doc.createElement('button');
  page.body.append(opener);
  opener.focus();
  inspector.openSheet(asked.id, opener);
  const sheet = page.ids.inspector;
  assert.equal(sheet.getAttribute('role'), 'dialog');
  assert.equal(sheet.getAttribute('aria-modal'), 'true');
  assert.equal(sheet.getAttribute('aria-labelledby'), 'behind-title');
  assert.equal(page.focused(), page.ids['behind-title']);
  for (const id of ['topbar', 'rail', 'main', 'tabbar']) assert.equal(page.ids[id].hasAttribute('inert'), true, id);
  assert.equal(page.ids.scrim.hidden, false);
  assert.equal(page.ids['behind-close'].hidden, false);
});

test('Tab stays inside the sheet, Escape closes it and gives the focus back to the control that opened it', () => {
  const sheet = page.ids.inspector;
  const close = page.ids['behind-close'];
  const key = (name, shift = false) => { const event = Object.assign(new Ev('keydown'), { key: name, shiftKey: shift }); sheet.dispatchEvent(event); return event; };
  close.focus();
  const tab = key('Tab');
  assert.equal(tab.defaultPrevented, false, 'the close button is the last stop of the sheet only if nothing follows it in the order');
  page.ids['behind-title'].focus();
  const back = key('Tab', true);
  assert.equal(back.defaultPrevented, true, 'Shift+Tab from the start goes to the end, not out of the sheet');
  key('Escape');
  assert.equal(sheet.getAttribute('role'), null);
  assert.equal(sheet.classList.contains('sheet'), false);
  assert.equal(page.ids.scrim.hidden, true);
  for (const id of ['topbar', 'rail', 'main', 'tabbar']) assert.equal(page.ids[id].hasAttribute('inert'), false, id);
  assert.equal(page.focused().tag, 'button', 'the focus is back on the control that opened it');
});

test('the sheet closes by itself when the screen grows to hold the inspector beside the stage', () => {
  reset();
  const asked = turn();
  store.addTurn(asked);
  inspector.openSheet(asked.id, null);
  assert.equal(page.ids.inspector.classList.contains('sheet'), true);
  page.setMedia('(min-width: 1280px)', true);
  assert.equal(page.ids.inspector.classList.contains('sheet'), false);
});

test('a sheet opened for the answer of another view shows that answer, whichever view the person is in', () => {
  reset();
  const call = turn({ view: 'teams', line: '#4 · ACME Bank Hackathon', rows: [hop({ title: 'Hackathon sandbox asked the AI workspace', system: 'AI workspace', evidence: [link('trace'), link('spend')] })] });
  store.addTurn(call);
  state.view = 'commands';                                         // the commands are a tab of their own: the inspector would draw nothing for this view
  bus.emit('view', 'commands');
  inspector.openSheet(call.id, null);
  assert.equal(page.ids['behind-subject'].textContent, '#4 · ACME Bank Hackathon');
  assert.equal(page.ids['behind-body'].querySelectorAll('.hop').length, 1);
  assert.deepEqual(labels(page.ids['behind-body']), ['Trace', 'Spend'], 'the sheet holds the same list, with the buttons of each hop');
  assert.equal(page.ids.behind.classList.contains('idle'), false);
  assert.equal(page.ids.inspector.classList.contains('sheet'), true);
  inspector.closeSheet({ back: false });
  state.view = 'assistant';
});

test('the sheet pins the answer it was opened for: one that comes while it is read does not take its place, and takes it when the sheet is closed', () => {
  reset();
  const first = turn({ line: 'first' });
  store.addTurn(first);
  inspector.openSheet(first.id, null);
  const second = turn({ line: 'second' });
  store.addTurn(second);
  assert.equal(state.selected.assistant, first.id, 'the reader\'s answer stays under their eyes');
  assert.equal(page.ids['behind-subject'].textContent, 'first');
  inspector.closeSheet({ back: false });
  assert.equal(state.selected.assistant, second.id, 'closed: the newest is the one that follows the conversation again');
  const older = turn({ line: 'older' });
  store.addTurn(older);
  store.selectTurn(first.id);
  inspector.openSheet(first.id, null);
  inspector.closeSheet({ back: false });
  assert.equal(state.selected.assistant, first.id, 'an answer the person chose stays chosen');
  assert.equal(state.pinned.assistant, true);
});

test('nothing is drawn again, and no scroll or focus lost, when what the inspector shows did not change', () => {
  reset();
  const shown = turn({ rows: [hop(), hop({ title: 'Ace called list_accounts' })] });
  store.addTurn(shown);
  store.addTurn(turn());
  store.selectTurn(shown.id);                                       // the person looks at an older answer
  const timeline = page.ids['behind-body'].firstElementChild;
  store.addTurn(turn({ view: 'teams' }));                           // an answer of another view
  bus.emit('selected', 'assistant');
  bus.emit('view', 'assistant');
  store.addTurn(turn());                                            // a newer answer while the person looks at an older one
  assert.equal(page.ids['behind-body'].firstElementChild, timeline, 'the same hops, not drawn again');
  const newest = turn();
  store.addTurn(newest, { select: true });
  assert.notEqual(page.ids['behind-body'].firstElementChild, timeline);
});

test('a turn that is taken back leaves the selection to the newest one left', () => {
  reset();
  const first = turn({ line: 'first' });
  const second = turn({ line: 'second' });
  store.addTurn(first);
  store.addTurn(second);
  store.dropTurn(second.id);
  assert.equal(state.selected.assistant, first.id);
  assert.equal(page.ids['behind-subject'].textContent, 'first');
  store.dropTurn(first.id);
  assert.equal(state.selected.assistant, null);
  assert.equal(page.ids.behind.classList.contains('idle'), true);
});

test('the control that opens the sheet is named like what it opens and opens it for its own answer', () => {
  reset();
  const asked = turn({ line: 'asked' });
  store.addTurn(asked);
  const button = inspector.behindButton(asked.id);
  assert.equal(text(button), 'Behind the answer');
  assert.equal(button.getAttribute('aria-label'), 'Behind the answer');
  assert.equal(button.classList.contains('hops-open'), true);
  page.body.append(button);
  button.click();
  assert.equal(page.ids.inspector.classList.contains('sheet'), true);
  assert.equal(page.ids['behind-subject'].textContent, 'asked');
  inspector.closeSheet({ back: false });
});

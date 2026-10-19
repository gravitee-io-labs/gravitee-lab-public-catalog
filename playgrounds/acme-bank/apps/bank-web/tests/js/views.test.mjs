/* The views that hold what a question or a command gave (the conversation, Teams, Developers) over a small DOM: what a screen reader is told, what happens when
   a call fails or is stopped, who answered, how a command is asked and what comes of it, and the run of the budget in Teams. */
import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

import { installDom, text, flush } from './dom-stub.mjs';

const IDS = ['conversation', 'message', 'send', 'announcer', 'toasts', 'open-tokens', 'composer', 'inspector', 'behind', 'behind-subject', 'behind-body',
  'monitor', 'team-monitor', 'dev-monitor', 'team-feed', 'team-button', 'team-name', 'team-menu', 'team-picker', 'team-budget', 'team-short', 'team-long', 'team-triple',
  'dev-feed', 'dev-limit', 'dev-send', 'dev-burst', 'dev-faq', 'dev-form', 'dev-message', 'view-developers', 'money-form', 'money-from', 'money-to', 'money-amount', 'money-ref', 'money-send', 'person-button'];
const page = installDom({ ids: IDS, media: { '(min-width: 1280px)': true } });
mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: 1_000_000 });
page.ids['team-menu'].hidden = true;
page.ids['team-picker'].append(page.ids['team-button'], page.ids['team-menu']);
page.ids['dev-form'].tag = 'form';
page.ids.message.tag = 'textarea';
page.ids['dev-burst'].append(page.doc.createElement('span'));

const { bus } = await import('../../static/js/dom.js');
const store = await import('../../static/js/store.js');
const chat = await import('../../static/js/chat.js');
const turns = await import('../../static/js/turns.js');
const teams = await import('../../static/js/teams.js');
const developers = await import('../../static/js/developers.js');
const money = await import('../../static/js/money.js');
const { askAs } = await import('../../static/js/session.js');
const { state } = store;

const ALICE = { id: 'alice', name: 'Alice Martin', role: 'customer', customer_id: 'C-1001', accounts: ['ACC-1001'], send: { from: 'ACC-1001', to: 'ACC-2001', amount: 10 } };
const BOB = { id: 'bob', name: 'Bob Chen', role: 'customer', customer_id: 'C-2001', accounts: ['ACC-2001'], send: { from: 'ACC-2001', to: 'ACC-1001', amount: 5 } };
const TINA = { id: 'tina', name: 'Tina Torres', role: 'teller', send: { from: 'ACC-9', to: 'ACC-8', amount: 1 } };
const LEAK = { id: 'leak-an-iban', label: 'Leak an IBAN', kind: 'chat', persona: 'alice', message: 'My IBAN is FR76', transfer: null, team: '', direct: false };
const DIRECT = { id: 'ask-ace-direct', label: 'Ask Ace without the gateway', kind: 'chat', persona: 'alice', message: 'Show my accounts and balances', transfer: null, team: '', direct: true };
const MOVE = { id: 'move-600-yourself', label: 'Move EUR 600 yourself', kind: 'money', persona: 'alice', message: '', transfer: { from_account: 'ACC-1001', to_account: 'ACC-2001', amount: 600 }, team: '', direct: false };
const BUDGET = { id: 'spend-hackathon-budget', label: 'Spend the Hackathon budget', kind: 'budget', persona: null, message: '', transfer: null, team: 'team-hackathon', direct: false };
state.personas = [ALICE, BOB, TINA];
state.persona = ALICE;
for (const id of ['send', 'message']) page.ids[id].disabled = false;

chat.initChat();
teams.initTeams();
developers.initDevelopers();
money.initMoney();

const hop = (extra = {}) => ({ kind: 'a2a', name: '', title: 'Alice asked Ace', system: 'A2A proxy', direct: false, outcome: 'ok', tone: 'ok', word: 'Answered', status: 200, ms: 120,
  summary: 'Ace received the question and answered.', facts: [], evidence: [], ...extra });
const links = (...kinds) => kinds.map((kind) => ({ kind, label: kind[0].toUpperCase() + kind.slice(1), url: `http://gamma.test/${kind}` }));
const answer = (extra = {}) => ({ answer: 'Your balance is EUR 4,820.55.', gateway: 'on', protected: true, ms: 120, rows: [hop()],
  who: { persona: 'alice', name: 'Alice Martin', role: 'customer', signed: ['alice', 'bob', 'tina'] }, ...extra });
const payment = (extra = {}) => hop({ kind: 'tool', title: 'Alice called transfer_funds', system: 'MCP proxy', summary: 'The bank\'s tool answered.', protected: true, ms: 80,
  who: { persona: 'alice', name: 'Alice Martin', role: 'customer', signed: ['alice', 'bob', 'tina'] }, ...extra });
const route = (fn) => { globalThis.fetch = async (path, options = {}) => { const out = await fn(path, options); return { ok: out.status === undefined || out.status < 400, status: out.status || 200, json: async () => out.body }; }; };
const said = async () => { mock.timers.tick(100); await flush(); return page.ids.announcer.textContent; };
const fresh = () => { state.persona = ALICE; state.signed = ['alice', 'bob', 'tina']; state.running = null; state.gateway = true; bus.emit('conversation-reset'); page.ids.toasts.replaceChildren(); };

test('a screen reader is told Ace\'s answer once, whoever asked it: a typed question and a command are heard alike', async () => {
  fresh();
  route(() => ({ body: answer() }));
  await chat.ask('Show my accounts');
  assert.equal(await said(), 'Ace says: Your balance is EUR 4,820.55.');
  const bubble = page.ids.conversation.querySelector('.msg.ace .bubble');
  assert.equal(bubble.getAttribute('tabindex'), null, 'nothing in the conversation is a stop of the keyboard but its controls');
  assert.equal(page.ids.conversation.getAttribute('tabindex'), null, 'the conversation is not a stop of the keyboard: no black frame around it');
  fresh();
  await chat.playChat(LEAK);
  assert.equal(await said(), 'Ace says: Your balance is EUR 4,820.55.', 'a command is heard like a question typed');
});

test('what is said of an answer is its first 200 characters as plain text, and Ace answered when it said nothing', () => {
  assert.equal(chat.spoken('**Bold** `code` | a | b'), 'Ace says: Bold code a b');
  assert.equal(chat.spoken('x'.repeat(500)), `Ace says: ${'x'.repeat(200)}...`);
  assert.equal(chat.spoken(''), 'Ace answered.');
  assert.equal(chat.spoken(null), 'Ace answered.');
});

test('a command that fails says it once, as an alert in the conversation, and the answer that did not come is selected like any: its call is Behind it', async () => {
  fresh();
  route(() => ({ status: 504, body: { error: 'Ace is not answering. Try again in a minute.' } }));
  await chat.playChat(LEAK);
  const problem = page.ids.conversation.querySelector('.msg.problem .bubble');
  assert.equal(problem.getAttribute('role'), 'alert');
  assert.equal(text(problem), 'Ace is not answering. Try again in a minute.');
  assert.doesNotMatch(await said(), /not answering/, 'the alert is read by the screen reader: the announcer does not say it again');
  assert.equal(await said(), '', 'and what it said of the wait ("Ace is working") is not left behind');
  assert.equal(page.ids.conversation.querySelector('.msg.problem').classList.contains('sel'), true);
  assert.ok(page.ids.conversation.querySelector('.msg.problem .hops-open'), 'where Behind the answer is a sheet it has its control too');
});

test('the wait is counted in the conversation, with a way out after a few seconds, for a command as for a question typed', async () => {
  fresh();
  let release;
  globalThis.fetch = () => new Promise((resolve) => { release = () => resolve({ ok: true, status: 200, json: async () => answer() }); });
  const done = chat.playChat(LEAK);
  await flush();
  const working = () => text(page.ids.conversation.querySelector('.working'));
  const stop = () => page.ids.conversation.querySelector('.working-row .stop');
  assert.equal(working(), 'Ace is working - 0 s');
  mock.timers.tick(1000);
  assert.equal(working(), 'Ace is working - 1 s');
  assert.equal(stop().hidden, true, 'no way out in the first seconds');
  mock.timers.tick(5000);
  assert.equal(working(), 'Ace is working - 6 s');
  assert.equal(stop().hidden, false);
  release();
  await done;
  assert.equal(page.ids.conversation.querySelector('.working'), null, 'the wait is gone with the answer');
});

test('Stop ends the call that is on its way and says the person stopped waiting', async () => {
  fresh();
  let signal = null;
  globalThis.fetch = (path, options) => new Promise((resolve, reject) => { signal = options.signal; signal.addEventListener('abort', () => reject(new Error('aborted'))); });
  const done = chat.playChat(LEAK);
  await flush();
  mock.timers.tick(6000);
  assert.ok(signal && !signal.aborted);
  page.ids.conversation.querySelector('.working-row .stop').click();
  assert.equal(await done, null);
  assert.equal(signal.aborted, true);
  assert.match(text(page.ids.conversation.querySelector('.msg.problem .bubble')), /You stopped waiting/);
});

test('an answer for the person another tab chose says whose it is', async () => {
  fresh();
  route(() => ({ body: answer({ who: { persona: 'tina', name: 'Tina Torres', role: 'teller' } }) }));
  await chat.ask('Show my accounts');
  assert.equal(state.persona.id, 'tina', 'the page follows the one who answered');
  assert.match(text(page.ids.toasts), /This answer is Tina Torres's: another tab of this page signed Tina Torres in\./);
  state.persona = ALICE;
});

test('a payment made while another tab signed somebody else in says whose it is, as an answer and as a refusal', async () => {
  const submit = async () => {
    page.ids['money-amount'].valueAsNumber = 5;
    page.ids['money-form'].dispatchEvent(new Event('submit'));
    await flush();
  };
  for (const [what, reply] of [['allowed', () => ({ body: payment({ who: { persona: 'tina', name: 'Tina Torres', role: 'teller' } }) })],
    ['refused', () => ({ status: 502, body: { error: 'The bank did not answer.', who: { persona: 'tina', name: 'Tina Torres', role: 'teller' } } })]]) {
    fresh();
    page.ids.toasts.replaceChildren();
    route(reply);
    await submit();
    assert.equal(state.persona.id, 'tina', `${what}: the page follows the one who paid`);
    assert.match(text(page.ids.toasts), /This answer is Tina Torres's: another tab of this page signed Tina Torres in\./, what);
  }
  state.persona = ALICE;
});

/* ---- commands --------------------------------------------------------------------------------------------------------------------- */

test('a command carries its own route: the switch in the head is never read by it, set either way; a question typed there reads it', async () => {
  const posted = [];
  route((path, options) => {
    posted.push([path, options.body ? JSON.parse(options.body) : undefined]);
    return { body: path.includes('move-600') ? payment() : answer() };
  });
  for (const head of [false, true]) {
    state.gateway = head;
    fresh();
    state.gateway = head;
    posted.length = 0;
    await chat.playChat(LEAK);
    await chat.playChat(DIRECT);
    await money.playMoney(MOVE);
    assert.deepEqual(posted, [['/api/commands/leak-an-iban/run', {}], ['/api/commands/ask-ace-direct/run', {}], ['/api/commands/move-600-yourself/run', {}]],
      `with the switch of the head ${head ? 'through the gateway' : 'direct'}: the command goes where the app says, and the page says nothing of it`);
  }
  for (const [head, said] of [[false, 'off'], [true, 'on']]) {
    fresh();
    state.gateway = head;
    posted.length = 0;
    await chat.ask('A question typed in the conversation');
    assert.deepEqual(posted, [['/api/chat', { message: 'A question typed in the conversation', gateway: said }]]);
  }
  state.gateway = true;
});

test('a command asks its question as a bubble of the person, shows the answer and selects it for Behind the answer', async () => {
  fresh();
  route(() => ({ body: answer({ rows: [hop({ evidence: links('trace', 'logs') })] }) }));
  await chat.ask('An older question');
  const older = store.turnsOf('assistant')[0];
  store.selectTurn(older.id);                                    // the person is reading an older answer
  await chat.playChat(LEAK);
  const turns = store.turnsOf('assistant');
  assert.deepEqual(page.ids.conversation.querySelectorAll('.msg.user').map((node) => text(node)), ['An older question', 'My IBAN is FR76']);
  assert.equal(state.selected.assistant, turns[1].id, 'the answer to a command is the one that is selected, whatever the person was reading');
  assert.equal(state.pinned.assistant, false);
  assert.deepEqual(turns[1].rows[0].evidence.map((e) => e.kind), ['trace', 'logs'], 'the answer\'s hops are the server\'s, each with the buttons of its own call');
  assert.equal(turns[1].line.endsWith('· My IBAN is FR76'), true);
});

test('after a command the conversation holds only turns, and no button of evidence: it is in the hops', async () => {
  fresh();
  route(() => ({ body: answer({ rows: [hop({ evidence: links('trace') })] }) }));
  await chat.playChat(LEAK);
  const log = page.ids.conversation;
  for (const node of log.children) assert.ok(node.classList.contains('msg'), `only turns: ${node.className}`);
  assert.equal(log.querySelectorAll('a').length, 0, 'no button of evidence in the conversation: each is in the hop of its own call, in Behind the answer');
});

test('a command that goes direct says so under its answer: Direct', async () => {
  fresh();
  route(() => ({ body: answer({ gateway: 'off', protected: false }) }));
  await chat.playChat(DIRECT);
  assert.equal(text(page.ids.conversation.querySelector('.msg.ace .meta .route')), 'Direct');
  assert.equal(state.turns.get(state.selected.assistant).gateway, false, 'and Behind the answer says nothing was recorded');
});

test('a conversation with no message says so in one line, whoever is asking: the same placeholder signed in and signed out, with the one Ace icon', () => {
  const lines = [];
  for (const asking of [ALICE, null, TINA]) {
    fresh();
    state.persona = asking;
    bus.emit('conversation-reset');
    const empty = page.ids.conversation.querySelector('[data-empty]');
    lines.push(text(empty));
    assert.equal(empty.querySelectorAll('svg').length, 1, 'the Ace icon, once');
    assert.equal(empty.querySelectorAll('button').length, 0, 'nothing to press: who asks is chosen in the head');
  }
  assert.deepEqual([...new Set(lines)], ['No message yet. Ask Ace a question, or run a command.']);
  state.persona = ALICE;
});

test('another person starts another conversation: nothing of the one before stays on the screen, folded or not, and nothing is said of it', async () => {
  fresh();
  route((path) => ({ body: path === '/api/session' ? { persona: 'bob', signed: ['alice', 'bob', 'tina'] } : answer() }));
  await chat.ask('Alice asks');
  assert.equal(store.turnsOf('assistant').length, 1);
  await askAs('alice');
  assert.equal(state.persona.id, 'alice', 'the person is who the command is for already: nothing changes');
  assert.equal(store.turnsOf('assistant').length, 1);
  await askAs('bob');
  assert.equal(state.persona.id, 'bob');
  assert.equal(store.turnsOf('assistant').length, 0);
  assert.equal(page.ids.conversation.querySelectorAll('.msg, details').length, 0);
  assert.equal(page.ids.toasts.children.length, 0, 'no toast: the head says who is asking');
  assert.equal(state.selected.assistant, null);
  state.persona = ALICE;
});

test('the answers of Teams and Developers are not a conversation: asking as somebody else leaves them where they are', async () => {
  fresh();
  state.turns.set('m1', { id: 'm1', view: 'teams', rows: [{}], at: 1 });
  route(() => ({ body: { persona: 'bob', signed: ['alice', 'bob', 'tina'] } }));
  await askAs('bob');
  assert.equal(state.persona.id, 'bob');
  assert.equal(state.turns.has('m1'), true);
  state.turns.delete('m1');
  state.persona = ALICE;
});

test('a payment that a command made is a turn of the conversation, a receipt, and it is selected', async () => {
  fresh();
  route(() => ({ body: payment({ evidence: links('logs') }) }));
  await money.playMoney(MOVE);
  const [turn] = store.turnsOf('assistant');
  assert.deepEqual([turn.kind, turn.view], ['payment', 'assistant']);
  assert.equal(state.selected.assistant, turn.id);
  const receipt = page.ids.conversation.querySelector(`[data-turn="${turn.id}"]`);
  assert.match(text(receipt), /EUR 600 from ACC-1001 to ACC-2001/);
  assert.match(text(receipt), /Moved/);
  assert.doesNotMatch(text(receipt), /reference/, 'the command sends no reference');
  assert.deepEqual(turn.rows[0].evidence.map((e) => e.kind), ['logs'], 'the payment is the one hop Behind it, with the buttons of its own call');
  assert.equal(await said(), 'Moved: EUR 600');
});

test('a payment the policy engine refused is a receipt that says Not moved, and its call is Behind it', async () => {
  fresh();
  route(() => ({ body: payment({ tone: 'deny', word: 'Denied by policy', status: 403, summary: 'Denied by policy: no' }) }));
  await money.playMoney(MOVE);
  assert.match(text(page.ids.conversation.querySelector('[data-turn]')), /Not moved/);
});

test('an answer is not chosen by the click that ends a selection of its words', async () => {
  fresh();
  route(() => ({ body: answer() }));
  await chat.ask('First');
  await chat.ask('Second');
  const [first, second] = store.turnsOf('assistant');
  assert.equal(state.selected.assistant, second.id);
  const nodes = page.ids.conversation.querySelectorAll('.msg.ace');
  globalThis.window.getSelection = () => 'some words of the answer';
  nodes[0].click();
  assert.equal(state.selected.assistant, second.id, 'somebody is selecting words, not choosing');
  globalThis.window.getSelection = () => '';
  nodes[0].click();
  assert.equal(state.selected.assistant, first.id);
  delete globalThis.window.getSelection;
});

test('Try again takes the failed answer back: it is not selected while the question is asked again', async () => {
  fresh();
  route(() => ({ status: 504, body: { error: 'Ace is not answering. Try again in a minute.' } }));
  await chat.ask('Will it work?');
  const failed = store.turnsOf('assistant')[0];
  assert.equal(state.selected.assistant, failed.id, 'a failed answer is an answer: it is selected and its call is Behind it');
  let release;
  route(() => new Promise((resolve) => { release = () => resolve({ body: answer() }); }));
  page.ids.conversation.querySelector('.problem-actions .btn').click();
  assert.equal(state.turns.has(failed.id), false);
  assert.equal(state.selected.assistant, null, 'nothing is selected while the question is on its way again');
  release();
  await flush();
  await flush();
  assert.equal(store.turnsOf('assistant').length, 1);
  assert.equal(store.turnsOf('assistant')[0].kind, 'chat');
  assert.equal(page.ids.conversation.querySelectorAll('.msg.user').length, 1, 'the question that got no answer is asked again, not shown twice');
});

/* ---- Teams: the answers of the workspace, and the run of the budget ----------------------------------------------------------------- */

const callOf = (n, left, { evidence = [], ...extra } = {}) => ({ team: 'team-hackathon', status: 200, answer: `answer ${n}`, model: 'smart', ms: 100, tokens: { total: 50 },
  rows: [hop({ kind: 'workspace', title: 'Hackathon sandbox asked the AI workspace', system: 'AI workspace', summary: 'The smart model answered, 50 tokens.', evidence })],
  budget: { limit: 0.12, left, percent_left: Math.round((100 * left) / 0.12) }, limits: { reset: 1_000_000 + 3600_000 }, ...extra });
const TEAMS = { teams: [{ id: 'team-hackathon', name: 'Hackathon sandbox' }, { id: 'team-b', name: 'Team B' }], spend: 'http://gamma.test/spend' };

test('an answer of a team is a turn: the newest is selected, a click chooses another, its call is the one hop Behind it, and the figures are said once', async () => {
  route((path) => {
    if (path === '/api/teams') return { body: TEAMS };
    return { body: callOf(1, 0.08, { evidence: [{ kind: 'logs', label: 'Logs', url: 'http://gamma.test/l' }, { kind: 'spend', label: 'Spend', url: 'http://gamma.test/spend' }, { kind: 'trace', label: 'Trace', url: '/api/evidence?kind=trace&api=teams&request=req-12345678&at=1' }] }) };
  });
  bus.emit('view', 'teams');
  await flush();
  page.ids['team-short'].click();
  await flush();
  route(() => ({ body: callOf(2, 0.05) }));
  page.ids['team-short'].click();
  await flush();
  const rows = page.ids['team-feed'].querySelectorAll('.answer');
  assert.deepEqual(rows.map((row) => text(row.querySelector('.num'))), ['#1', '#2'], 'oldest first, like the conversation');
  assert.equal(state.selected.teams, 'm2');
  assert.equal(rows[1].classList.contains('sel'), true);
  assert.equal(rows[0].classList.contains('sel'), false);
  rows[0].click();
  assert.equal(state.selected.teams, 'm1');
  assert.equal(rows[0].classList.contains('sel'), true);
  const turn = state.turns.get('m1');
  assert.equal(turn.view, 'teams');
  assert.equal(turn.line, '#1 · Hackathon sandbox');
  assert.equal(turn.rows.length, 1);
  assert.deepEqual(turn.rows[0].evidence.map((e) => e.kind), ['logs', 'spend', 'trace'], 'Spend is one of the evidence of the call, with Trace and Logs: it is not a button of the monitor');
  assert.equal(turn.rows[0].title, 'Hackathon sandbox asked the AI workspace', 'the hop is the server\'s: the page names nothing');
  assert.equal(turn.rows[0].summary, 'The smart model answered, 50 tokens.', 'the model is said by the answer\'s own chip, once, and by the hop in its own words');
  assert.equal(text(rows[0].querySelector('.answer-top')).includes('tokens'), false, 'tokens and time are the call\'s, Behind the answer: not said in the answer too');
  assert.equal(text(rows[0].querySelector('.hops-open')), 'Behind the answer');
  assert.match(text(page.ids['team-budget']), /\$0\.05\s*left of \$0\.12/, 'what is left, said once, by the monitor');
  assert.equal(text(page.ids['team-budget']).includes('% left'), false);
  assert.match(text(rows[0].querySelector('.answer-top')), /\d+% spent/, 'and what each answer was let in at, said by the answer');
});

test('the team that calls is chosen in the head: a menu, and the figures are the budget of that team', async () => {
  const button = page.ids['team-button'];
  const menu = page.ids['team-menu'];
  button.click();
  assert.deepEqual(menu.querySelectorAll('.menu-item').map((item) => text(item)), ['Hackathon sandbox', 'Team B']);
  assert.equal(menu.querySelectorAll('.menu-item')[0].getAttribute('aria-checked'), 'true');
  menu.querySelectorAll('.menu-item')[1].click();
  assert.equal(state.team, 'team-b');
  assert.equal(text(page.ids['team-name']), 'Team B');
  assert.equal(menu.hidden, true);
  assert.match(text(page.ids['team-budget']), /no call yet/, 'nothing is known of that team\'s budget yet');
  state.team = 'team-hackathon';
});

test('the budget command is a run of long answers of the Hackathon team, one request each, and it ends at the first that is not an answer', async () => {
  fresh();
  const asked = [];
  let n = 0;
  route((path, options) => {
    if (path === '/api/teams') return { body: TEAMS };
    n += 1;
    asked.push([path, JSON.parse(options.body)]);
    return { body: n < 3 ? callOf(n, 0.12 - 0.03 * n) : callOf(n, 0, { status: 429, answer: undefined, message: 'Cost budget exceeded!', model: null }) };
  });
  state.budgetCalls = 4;
  state.team = 'team-b';
  const before = state.turns.size;
  await teams.runBudget(BUDGET);
  assert.equal(state.team, 'team-hackathon', 'the team of the command is the one that calls');
  assert.equal(text(page.ids['team-name']), 'Hackathon sandbox');
  assert.equal(asked.length, 3, 'two answers and the 429, which ends the run: not four');
  assert.deepEqual(asked.map(([path]) => path), ['/api/teams/chat', '/api/teams/chat', '/api/teams/chat']);
  assert.deepEqual(asked.map(([, body]) => body.team), ['team-hackathon', 'team-hackathon', 'team-hackathon']);
  assert.deepEqual(asked.map(([, body]) => body.kind), ['long', 'long', 'long']);
  assert.equal(new Set(asked.map(([, body]) => body.since)).size, 1, 'every answer says when the run began, so that its Spend is the whole run\'s');
  assert.ok(Number.isInteger(asked[0][1].since));
  assert.equal(state.turns.size - before, 3);
  const rows = page.ids['team-feed'].querySelectorAll('.answer');
  assert.doesNotMatch(text(rows.at(-1)), /429|Limited/, 'the status of the call is Behind the answer, in its hop: once');
  assert.match(text(rows.at(-1)), /Cost budget exceeded!/, 'the 429 says what the gateway said');
  assert.equal(state.selected.teams, `m${rows.length}`, 'the last answer of the run is the one selected, for Behind the answer');
  assert.equal(page.ids['team-feed'].querySelector('.typing'), null, 'the dots of a call on its way are gone');
});

test('the budget command asks for as many answers as the app says and no more, and the last one is selected whatever the person was reading', async () => {
  fresh();
  let asked = 0;
  route((path) => {
    if (path === '/api/teams') return { body: TEAMS };
    asked += 1;
    return { body: callOf(asked, 0.1) };
  });
  state.budgetCalls = 2;
  const older = [...state.turns.keys()].find((id) => id.startsWith('m'));
  store.selectTurn(older);                                            // the person is reading an older answer of Teams
  await teams.runBudget(BUDGET);
  assert.equal(asked, 2);
  const last = [...state.turns.keys()].filter((id) => id.startsWith('m')).at(-1);
  assert.notEqual(last, older);
  assert.equal(state.selected.teams, last, 'the answer to a command is selected whatever the person was reading');
  assert.equal(state.pinned.teams, false);
  state.budgetCalls = 4;
});

test('a call that is on its way shows dots at the end of the feed, and the buttons wait', async () => {
  let release;
  route((path) => {
    if (path === '/api/teams') return { body: TEAMS };
    return new Promise((resolve) => { release = () => resolve({ body: callOf(9, 0.1) }); });
  });
  page.ids['team-long'].click();
  await flush();
  assert.ok(page.ids['team-feed'].querySelector('.typing'));
  assert.equal(page.ids['team-long'].disabled, true);
  release();
  await flush();
  await flush();
  assert.equal(page.ids['team-feed'].querySelector('.typing'), null);
  assert.equal(page.ids['team-long'].disabled, false);
});

test('Long answer x3 is a run of three, with one start for the whole of it, and it ends at the first that is not an answer', async () => {
  let n = 0;
  const bodies = [];
  route((path, options) => {
    if (path === '/api/teams') return { body: TEAMS };
    n += 1;
    bodies.push(JSON.parse(options.body));
    return { body: n === 2 ? callOf(n, 0, { status: 429, message: 'Cost budget exceeded!', model: null }) : callOf(n, 0.1) };
  });
  state.team = 'team-hackathon';
  page.ids['team-triple'].click();
  await flush();
  await flush();
  await flush();
  assert.equal(bodies.length, 2, 'the 429 is the answer: a third would say nothing more');
  assert.equal(bodies[0].since, bodies[1].since);
  page.ids['team-short'].click();
  await flush();
  await flush();
  assert.equal('since' in bodies.at(-1), false, 'one answer alone is its own run: the app finds where it began');
});

/* ---- Developers ------------------------------------------------------------------------------------------------------------------ */

test('an answer of the LLM proxy is a turn of Developers, selected as it comes, with its tokens left in the monitor', async () => {
  route(() => ({ body: { status: 200, answer: 'A mortgage is a loan.', model: 'smart', ms: 300, tokens: { total: 90 }, rows: [hop({ kind: 'llm', title: 'A developer asked the model', system: 'LLM proxy' })], question: 'Explain a mortgage', limits: { limit: 3000, remaining: 2100, reset: 1_000_000 + 30_000 } } }));
  page.ids['dev-message'].value = 'Explain a mortgage';
  page.ids['dev-form'].dispatchEvent(new Event('submit'));
  await flush();
  await flush();
  assert.equal(page.ids['dev-feed'].querySelectorAll('.answer').length, 1);
  assert.equal(state.selected.developers, 'd1');
  assert.match(text(page.ids['dev-limit']), /2,100\s*left of 3,000/);
});

/* ---- what a narrow window needs: the end of a scroller, Send, a call on its way --------------------------- */

test('no answer carries evidence under it: a conversation answer, a payment, an answer of a team, an answer of the proxy have it in their hops, Behind the answer', async () => {
  fresh();
  const drawn = (node) => node.querySelectorAll('a, .hop-evidence').length;
  route(() => ({ body: answer({ rows: [hop({ evidence: links('logs', 'trace') })] }) }));
  await chat.playChat(LEAK);
  assert.equal(drawn(page.ids.conversation.querySelector('.msg.ace')), 0);
  route(() => ({ body: payment({ evidence: links('logs', 'trace') }) }));
  await money.playMoney(MOVE);
  assert.equal(drawn(page.ids.conversation.querySelector('.msg.pay[data-turn]')), 0);
  route((path) => (path === '/api/teams' ? { body: TEAMS } : { body: callOf(1, 0.08, { evidence: links('spend', 'logs', 'trace') }) }));
  bus.emit('view', 'teams');
  await flush();
  page.ids['team-short'].click();
  await flush();
  assert.equal(drawn(page.ids['team-feed'].querySelectorAll('.answer').at(-1)), 0);
  assert.deepEqual(state.turns.get(state.selected.teams).rows[0].evidence.map((e) => e.kind), ['spend', 'logs', 'trace'], 'it is in the hop');
  route(() => ({ body: { status: 200, answer: 'A loan.', model: 'smart', ms: 300, tokens: { total: 90 }, rows: [hop({ kind: 'llm', evidence: links('logs', 'trace') })], question: 'q', limits: null } }));
  page.ids['dev-message'].value = 'q';
  page.ids['dev-form'].dispatchEvent(new Event('submit'));
  await flush();
  await flush();
  assert.equal(drawn(page.ids['dev-feed'].querySelectorAll('.answer').at(-1)), 0);
});

test('an answer that failed is one hop of its own, the gateway\'s when the server has it and the page\'s when it has not: Behind the answer is never empty of it', async () => {
  fresh();
  route(() => ({ status: 504, body: { error: 'Ace is not answering. Try again in a minute.', who: { persona: 'alice' } } }));
  await chat.ask('Will it work?');
  const [own] = state.turns.get(state.selected.assistant).rows;
  assert.deepEqual([own.title, own.system, own.status, own.tone, own.word, own.summary], ['Alice asked Ace', null, 504, 'error', 'Error', 'Error: Ace is not answering. Try again in a minute.']);
  assert.deepEqual([own.evidence, own.facts], [[], []], 'the page knows no request: no button');
  fresh();
  route(() => ({ status: 401, body: { error: 'The gateway did not accept your sign-in.', rows: [hop({ tone: 'deny', word: 'Unauthorized', status: 401, summary: 'Unauthorized.', evidence: links('logs') })] } }));
  await chat.ask('No token');
  const [sent] = state.turns.get(state.selected.assistant).rows;
  assert.deepEqual([sent.title, sent.system, sent.status, sent.summary], ['Alice asked Ace', 'A2A proxy', 401, 'Unauthorized.']);
  assert.deepEqual(sent.evidence.map((e) => e.kind), ['logs'], 'the gateway answered: the log of that call is there');
  fresh();
  route(() => ({ status: 502, body: { error: 'The bank did not answer.' } }));
  await money.playMoney(MOVE);
  assert.equal(state.turns.get(state.selected.assistant).rows[0].title, 'Alice called transfer_funds');
  state.persona = ALICE;
});

test('an answer that went direct and a failed one have no evidence row to draw: no row, no empty box', async () => {
  fresh();
  route(() => ({ body: answer({ gateway: 'off', protected: false, rows: [hop({ system: 'No gateway', direct: true })] }) }));
  await chat.playChat(DIRECT);
  assert.equal(page.ids.conversation.querySelectorAll('.hop-evidence').length, 0);
  assert.equal(state.turns.get(state.selected.assistant).rows[0].evidence.length, 0);
  route(() => ({ status: 502, body: { error: 'bad gateway', who: { persona: 'alice' } } }));
  await chat.ask('Again');
  assert.equal(page.ids.conversation.querySelectorAll('.hop-evidence').length, 0);
});

test('the end of a scroller is taken again once what was added is measured: a clamped answer gets its Show more a frame later', () => {
  const calls = [];
  const el = { scrollHeight: 400, scrollTo: ({ top }) => calls.push(top) };
  turns.toEnd(el);
  assert.deepEqual(calls, [400], 'at once');
  el.scrollHeight = 428;          // the Show more button came, and the end is lower
  mock.timers.tick(0);
  mock.timers.tick(0);
  assert.deepEqual(calls, [400, 428], 'and again two frames later, where the end is by then');
});

test('Send is for a question: it waits for words and for the answer before; where nobody is asking the menu of who is asking opens and the question stays in the box', async () => {
  fresh();
  const send = page.ids.send, message = page.ids.message;
  message.value = '';
  message.dispatchEvent(new Event('input'));
  assert.equal(send.disabled, true, 'nothing to send');
  message.value = '  ';
  message.dispatchEvent(new Event('input'));
  assert.equal(send.disabled, true, 'blanks are nothing');
  message.value = 'Show my accounts';
  message.dispatchEvent(new Event('input'));
  assert.equal(send.disabled, false);
  state.persona = null;
  bus.emit('persona', { changed: false });
  assert.equal(send.disabled, false, 'nobody is asking: the box is not a dead one, and Send is not either');
  assert.equal(message.disabled, false);
  let menus = 0;
  const sent = [];
  route((path) => { sent.push(path); return { body: answer() }; });
  page.ids['person-button'].addEventListener('click', () => { menus += 1; });
  assert.equal(await chat.ask(message.value), null);
  assert.deepEqual([menus, message.value, sent.length], [1, 'Show my accounts', 0], 'the menu opened, the question is still in the box, nothing was asked');
  state.persona = ALICE;
  bus.emit('persona', { changed: false });
  assert.equal(send.disabled, false);
  message.value = '';
});

test('a call of the LLM proxy on its way shows its dots in the feed, like the others, and they go when it is answered', async () => {
  let release = () => {};
  globalThis.fetch = async () => { await new Promise((resolve) => { release = resolve; }); return { ok: true, status: 200, json: async () => ({ status: 200, answer: 'A.', model: 'smart', ms: 1, tokens: { total: 1 }, rows: [hop()], question: 'q', limits: null }) }; };
  page.ids['dev-message'].value = 'q';
  page.ids['dev-form'].dispatchEvent(new Event('submit'));
  await flush();
  assert.equal(page.ids['dev-feed'].querySelectorAll('.msg.ace[aria-busy="true"] .dots').length, 1, 'something is working');
  assert.equal(page.ids['dev-feed'].querySelectorAll('.empty').length, 0, 'and the feed does not say there is no answer');
  release();
  await flush();
  await flush();
  assert.equal(page.ids['dev-feed'].querySelectorAll('[aria-busy="true"]').length, 0);
});

test('no answer of a team or of a developer has a chip for its status: how the call went is its hop\'s, Behind the answer', async () => {
  const ui = await import('../../static/js/ui.js');
  assert.equal(ui.statusChip, undefined);
  assert.equal(Object.hasOwn(ui, 'chip'), true, 'the chips that say which model answered and how much was spent stay');
});

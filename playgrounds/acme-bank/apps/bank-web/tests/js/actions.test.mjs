/* What the guide can ask of the page, inside the Lab UI: {type: "gravitee-lab:action", id} from the page's own parent runs the command of that id exactly as its
   button does, and nothing else does. Run for real over a small DOM: the page's own listener, the real rail, the real conversation and Teams, and a fetch that
   answers what the app would. The rules of acceptance are tried with what a page that is not the Lab UI could send. */
import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

import { flush, installDom, text } from './dom-stub.mjs';

const IDS = ['rail', 'shell', 'conversation', 'message', 'send', 'announcer', 'toasts', 'open-tokens', 'composer', 'inspector', 'behind', 'behind-subject',
  'behind-body', 'monitor', 'team-monitor', 'team-feed', 'team-button', 'team-name', 'team-menu', 'team-picker', 'team-budget', 'team-short', 'team-long', 'team-triple',
  'money-form', 'money-from', 'money-to', 'money-amount', 'money-ref', 'money-send', 'behind-title', 'behind-close', 'scrim'];
const page = installDom({ ids: IDS, media: { '(max-width: 639px)': false, '(min-width: 1280px)': true } });
mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: 1_000_000 });
page.ids.rail.tabIndex = -1;
page.ids['team-menu'].hidden = true;
page.ids['team-picker'].append(page.ids['team-button'], page.ids['team-menu']);
page.ids.message.tag = 'textarea';
page.ids.scrim.hidden = true;
page.ids['behind-close'].tag = 'button';
page.ids['behind-close'].hidden = true;

const { bus } = await import('../../static/js/dom.js');
const store = await import('../../static/js/store.js');
const chat = await import('../../static/js/chat.js');
const teams = await import('../../static/js/teams.js');
const money = await import('../../static/js/money.js');
const commands = await import('../../static/js/commands.js');
const inspector = await import('../../static/js/inspector.js');
const { LAB_ORIGINS } = await import('../../static/js/embed.js');
const { actionOf, initActions } = await import('../../static/js/actions.js');
const { state } = store;

const PEOPLE = {
  alice: { id: 'alice', name: 'Alice Martin', role: 'customer', send: { from: 'ACC-1001', to: 'ACC-2001', amount: 10 } },
  bob: { id: 'bob', name: 'Bob Chen', role: 'customer', send: { from: 'ACC-2001', to: 'ACC-1001', amount: 5 } },
  tina: { id: 'tina', name: 'Tina Torres', role: 'teller', send: { from: 'ACC-9', to: 'ACC-8', amount: 1 } },
};
const command = (id, label, persona, kind = 'chat', extra = {}) => ({ id, label, kind, persona, message: `question of ${id}`, transfer: null, team: '', direct: false, ...extra });
const GROUPS = [
  { id: 1, title: 'See everything', commands: [command('ask-ace-accounts', 'Ask Ace about my accounts', 'alice'), command('ask-ace-direct', 'Ask Ace without the gateway', 'alice', 'chat', { direct: true })] },
  { id: 2, title: 'Protect the model', commands: [command('leak-an-iban', 'Leak an IBAN', 'alice'), command('inject-a-prompt', 'Inject a prompt', 'alice')] },
  { id: 3, title: 'Protect the tools', commands: [command('freeze-card-customer', 'Freeze a card as a customer', 'alice'), command('freeze-card-teller', 'Freeze a card as a teller', 'tina')] },
  { id: 4, title: 'Decide who may do what', commands: [command('read-other-accounts', "Read another customer's accounts", 'bob')] },
  { id: 5, title: 'Cap what an agent may do', commands: [command('move-600-through-ace', 'Move EUR 600 through Ace', 'alice'),
    command('move-600-yourself', 'Move EUR 600 yourself', 'alice', 'money', { transfer: { from_account: 'ACC-1001', to_account: 'ACC-2001', amount: 600 } })] },
  { id: 6, title: 'Cap what teams spend', commands: [command('spend-hackathon-budget', 'Spend the Hackathon budget', null, 'budget', { team: 'team-hackathon' })] },
];
const ALL = GROUPS.flatMap((group) => group.commands);
const IDS_OF_THE_GUIDE = ['ask-ace-accounts', 'ask-ace-direct', 'leak-an-iban', 'inject-a-prompt', 'freeze-card-customer', 'freeze-card-teller', 'read-other-accounts', 'move-600-through-ace',
  'move-600-yourself', 'spend-hackathon-budget'];

/* What the app would answer, and what was asked of it. */
const asked = [];
const TEAMS = { teams: [{ id: 'team-hackathon', name: 'Hackathon sandbox' }], spend: 'http://gamma.test/spend' };
const HOP = { kind: 'a2a', name: '', title: 'Alice asked Ace', system: 'A2A proxy', direct: false, outcome: 'ok', tone: 'ok', word: 'Answered', status: 200, ms: 100, summary: 'Ace received the question and answered.', facts: [], evidence: [] };
let calls = 0;
const server = { signed: ['alice', 'bob', 'tina'] };            // who the server holds a token for
globalThis.fetch = async (path, options = {}) => {
  const body = options.body ? JSON.parse(options.body) : null;
  asked.push(`${options.method || 'GET'} ${path}${path === '/api/session' ? ` ${body.persona}` : ''}`);
  const run = ALL.find((one) => path === `/api/commands/${one.id}/run`);
  let out = { error: 'no route' };
  let status = 404;
  const who = (persona) => ({ persona, signed: [...server.signed] });
  const nobody = { ...HOP, title: 'Someone not signed in asked Ace', outcome: 'unauthorized', tone: 'deny', word: 'Unauthorized', status: 401, summary: 'Unauthorized: no token was sent' };
  if (path === '/api/session') [out, status] = [who(body.persona), 200];
  else if (path === '/api/teams') [out, status] = [TEAMS, 200];
  else if (path === '/api/teams/chat') {
    calls += 1;
    [out, status] = [{ team: 'team-hackathon', status: 200, answer: `answer ${calls}`, model: 'smart', ms: 100, tokens: { total: 50 }, rows: [HOP],
      budget: { limit: 0.12, left: 0.12 - 0.03 * calls, percent_left: 100 - 25 * calls }, limits: { reset: 1_000_000 + 3600_000 } }, 200];
  } else if (run && run.kind === 'chat' && !server.signed.includes(run.persona)) {
    [out, status] = [{ error: 'The gateway refused the question: it asks for a token, and none was sent.', rows: [nobody], who: who(state.persona && state.persona.id) }, 401];
  } else if (run && run.kind === 'money' && !server.signed.includes(run.persona)) [out, status] = [{ ...nobody, kind: 'tool', title: 'Someone not signed in called transfer_funds', system: 'MCP proxy', protected: true, who: who(state.persona && state.persona.id) }, 200];
  else if (run && run.kind === 'money') [out, status] = [{ ...HOP, protected: true, ms: 80, who: PEOPLE[run.persona] && who(run.persona) }, 200];
  else if (run) [out, status] = [{ answer: `answer to ${run.id}`, gateway: 'on', protected: true, ms: 120, rows: [HOP], who: who(run.persona) }, 200];
  return { ok: status < 400, status, json: async () => out };
};

state.personas = Object.values(PEOPLE);
state.persona = PEOPLE.alice;
state.signed = ['alice', 'bob', 'tina'];
state.groups = GROUPS;
state.budgetCalls = 3;
chat.initChat();
teams.initTeams();
money.initMoney();
commands.initCommands();

const went = [];
const running = [];
bus.on('go', (view) => went.push(view));
bus.on('running', () => running.push(state.running));
const lab = { postMessage: (message, origin) => told.push({ message, origin }) };           // the page's own parent
const told = [];
const toasts = () => text(page.ids.toasts);
const button = (id) => page.ids.rail.querySelector(`[data-key="${id}"]`);

function fresh(signed = ['alice', 'bob', 'tina']) {
  server.signed = [...signed];
  state.persona = PEOPLE.alice;
  state.signed = [...signed];
  state.running = null;
  state.gateway = true;
  state.groups = GROUPS;
  calls = 0;
  bus.emit('conversation-reset');
  store.forgetTurns('teams');
  page.ids['team-feed'].replaceChildren();
  page.ids.toasts.replaceChildren();
  page.doc.blurred = false;
  asked.length = 0;
  went.length = 0;
  running.length = 0;
}

async function settle() {
  for (let round = 0; round < 12; round += 1) {
    await flush();
    mock.timers.tick(60);
  }
}

/* What the person sees and what the page asked after a command ran, whichever way it was asked. Turn numbers are left out: they count what ran before. */
function after() {
  return {
    asked: asked.filter((one) => one !== 'GET /api/teams'),          // the list of teams is read once, by whichever run comes first
    went: [...went],
    person: state.persona && state.persona.id,
    selected: Object.fromEntries(Object.entries(state.selected).map(([view, id]) => [view, id ? ((turn) => ({ kind: turn.kind, line: turn.line.replace(/^#\d+/, '#') }))(state.turns.get(id)) : null])),
    conversation: text(page.ids.conversation),
    team: text(page.ids['team-feed']).replace(/#\d+/g, '#'),
  };
}

const send = (data, from = {}) => page.fire('window', 'message', { data, source: lab, origin: LAB_ORIGINS[0], ...from });      // `from` may say undefined: that is not the default
const action = (id) => ({ type: 'gravitee-lab:action', id });

/* ---- standalone, then framed ----------------------------------------------------------------------------------------------------- */

test('standalone nothing listens and nothing is said: a message that looks like an action does nothing', async () => {
  fresh();
  initActions();
  assert.equal((globalThis.window.listeners.message || []).length, 0, 'no listener');
  send(action('leak-an-iban'), { source: globalThis.window, origin: LAB_ORIGINS[0] });
  await settle();
  assert.deepEqual([asked, went, running], [[], [], []]);
});

test('framed, once the listener is installed the page says it is ready, to the Lab UI and to nobody else, and says nothing more', () => {
  globalThis.window.parent = lab;
  initActions();
  assert.deepEqual([...new Set(told.map((one) => JSON.stringify(one.message)))], [JSON.stringify({ type: 'gravitee-lab:ready' })]);
  assert.deepEqual(told.map((one) => one.origin), LAB_ORIGINS, 'each of the Lab UI\'s origins, since the browser does not say who the parent is; never any origin');
  assert.equal(told.some((one) => one.origin === '*'), false);
  assert.equal(globalThis.window.listeners.message.length, 1, 'one listener');
});

/* ---- what a click does is what an action does -------------------------------------------------------------------------------------- */

test('every id of the guide is a command of the app, and an action runs it exactly as its button does: the person, the question or the payment or the budget, the answer and what is selected', async () => {
  assert.deepEqual(ALL.map((one) => one.id), IDS_OF_THE_GUIDE);
  for (const one of ALL) {
    fresh();
    button(one.id).click();
    await settle();
    const clicked = after();
    assert.ok(clicked.asked.length > 0, `${one.id}: the click asked something`);
    fresh();
    send(action(one.id));
    await settle();
    assert.deepEqual(after(), clicked, `${one.id}: the same requests, the same view, the same person, the same answer, the same selection`);
    assert.equal(state.running, null);
  }
});

test('it asks as the person the command is for, who is signed in, as the button does, and the budget goes to Teams', async () => {
  fresh();
  send(action('freeze-card-teller'));
  await settle();
  assert.deepEqual(asked, ['POST /api/session tina', 'POST /api/commands/freeze-card-teller/run']);
  assert.equal(state.persona.id, 'tina');
  assert.match(text(page.ids.conversation), /answer to freeze-card-teller/);
  fresh();
  send(action('spend-hackathon-budget'));
  await settle();
  assert.deepEqual(went, ['teams']);
  assert.equal(asked.filter((one) => one === 'POST /api/teams/chat').length, 3);
  assert.equal(state.turns.get(state.selected.teams).kind, 'team', 'the last answer of the run is the one selected');
});

test('an action for somebody who is not signed in runs the command as it is, with no token, and opens no window: the gateway says no, and the refusal is the answer', async () => {
  fresh(['alice']);
  let windows = 0;
  globalThis.window.open = () => { windows += 1; return null; };
  send(action('read-other-accounts'));
  await settle();
  assert.equal(windows, 0, 'a command never signs anybody in: the person control does');
  assert.deepEqual(asked, ['POST /api/commands/read-other-accounts/run'], 'no switch to Bob, who is not signed in: the command goes as it is');
  assert.equal(state.persona.id, 'alice', 'who asks does not change');
  const refused = page.ids.conversation.querySelector('.msg.problem');
  assert.match(text(refused), /The gateway refused the question: it asks for a token, and none was sent\./);
  assert.doesNotMatch(text(page.ids.conversation), /sign-in window/, 'nothing of a window to open or to allow');
  assert.deepEqual([state.turns.get(state.selected.assistant).rows[0].title, state.turns.get(state.selected.assistant).rows[0].status], ['Someone not signed in asked Ace', 401]);
  assert.equal(state.running, null);
  assert.equal(store.isBusy(), false);
  delete globalThis.window.open;
});

test('the focus stays where the person is, in the guide: the page does not have it, so it does not take it; a click on its own button gives it back to the button', async () => {
  fresh();
  page.doc.blurred = true;
  const [before, focuses] = [page.focused(), button('leak-an-iban').focused];
  send(action('leak-an-iban'));
  await settle();
  assert.ok(page.focused() === before, 'the focus did not move');          // not assert.equal: a failure would print the whole page
  assert.equal(button('leak-an-iban').focused, focuses, 'the command was not focused');
  fresh();
  button('leak-an-iban').click();
  await settle();
  assert.ok(page.focused() === button('leak-an-iban'), 'the person who clicked goes on from there');
});

test('while something runs an action is told so, as a click is, and starts nothing', async () => {
  fresh();
  state.running = 'something';
  send(action('leak-an-iban'));
  await settle();
  assert.match(toasts(), /Something is still running\. Run it when it is done\./);
  assert.deepEqual([asked, went], [[], []]);
  state.running = null;
});

/* ---- what the page does not act on ----------------------------------------------------------------------------------------------- */

test('a message from another window, or from another origin, is not acted on, however well it is made: the page hears its own parent, the Lab UI, and no one else', async () => {
  fresh();
  const frame = { postMessage() {} };
  for (const source of [frame, globalThis.window, null, undefined, {}]) {
    send(action('leak-an-iban'), { source });
    assert.equal(actionOf({ source, origin: LAB_ORIGINS[0], data: action('leak-an-iban') }), null, `source ${String(source)}`);
  }
  for (const origin of ['https://evil.example', 'http://localhost:9001', 'http://localhost:9000.evil.example', 'http://localhost:8110', 'https://localhost:9000', 'http://127.0.0.1:9001',
    'http://evil.example:9000', 'null', '', undefined, null, '*']) {
    send(action('leak-an-iban'), { origin });
    assert.equal(actionOf({ source: lab, origin, data: action('leak-an-iban') }), null, `origin ${String(origin)}`);
  }
  await settle();
  assert.deepEqual([asked, went, running, toasts()], [[], [], [], ''], 'nothing ran, nothing was said');
  for (const origin of LAB_ORIGINS) assert.equal(actionOf({ source: lab, origin, data: action('leak-an-iban') }), 'leak-an-iban', origin);
});

test('what is not an action, or has no id the Lab UI could have drawn, is not acted on and says nothing', async () => {
  fresh();
  const odd = [null, undefined, 'gravitee-lab:action', 5, true, [], [action('leak-an-iban')], {}, { type: 'gravitee-lab:action' }, { id: 'leak-an-iban' },
    { type: 'gravitee-lab:open', id: 'leak-an-iban' }, { type: 'gravitee-lab:ready', id: 'leak-an-iban' }, { type: 'gravitee-lab:Action', id: 'leak-an-iban' }, { type: ['gravitee-lab:action'], id: 'leak-an-iban' },
    action(5), action(null), action(['leak-an-iban']), action({ toString: () => 'leak-an-iban' }), action(''), action('Leak-An-IBAN'), action('-leak'), action('leak an iban'), action('leak_an_iban'),
    action('../leak'), action('leak-an-iban '), action(' leak-an-iban'), action('leak-an-iban\n'), action('__proto__'), action('<b>x</b>')];
  for (const data of odd) {
    send(data);
    assert.equal(actionOf({ source: lab, origin: LAB_ORIGINS[0], data }), null, JSON.stringify(data));
  }
  await settle();
  assert.deepEqual([asked, went, running, toasts()], [[], [], [], '']);
});

test('an id that is not a command of the app shows a calm notice that names it, and runs nothing; with no commands the notice says so', async () => {
  fresh();
  send(action('no-such-command'));
  assert.match(toasts(), /The app has no command "no-such-command"\./);
  assert.equal(page.ids.toasts.querySelectorAll('.toast.info').length, 1, 'a calm notice, not an alert');
  assert.equal(page.ids.toasts.querySelectorAll('[role="alert"]').length, 0);
  fresh();
  send(action('constructor'));
  assert.match(toasts(), /The app has no command "constructor"\./, 'what an object has by itself is no command');
  fresh();
  send(action('leak-an-iban-2'));
  assert.match(toasts(), /no command "leak-an-iban-2"/, 'a name that is nearly one is not run');
  fresh();
  state.groups = [];
  send(action('leak-an-iban'));
  assert.match(toasts(), /The commands are not available\./);
  await settle();
  assert.deepEqual([asked, went, running], [[], [], []]);
  state.groups = GROUPS;
});

test('the README lists the ids of the commands, which are what a guide names in an action link', async () => {
  const { readFile } = await import('node:fs/promises');
  const readme = await readFile(new URL('../../README.md', import.meta.url), 'utf8');
  for (const id of IDS_OF_THE_GUIDE) assert.ok(readme.includes(`\`${id}\``), `the README does not list ${id}`);
});

test('the page answers nothing: of all this, the one thing it said to the Lab UI is that it is ready', () => {
  assert.deepEqual([...new Set(told.map((one) => one.message.type))], ['gravitee-lab:ready']);
  assert.equal(told.length, LAB_ORIGINS.length);
});

test('where Behind the answer is a sheet it is closed first, so that the answer of the command is the one in front of the person; the focus stays in the guide', async () => {
  fresh();
  send(action('ask-ace-accounts'));
  await settle();
  const read = state.selected.assistant;
  inspector.openSheet(read, null);
  assert.equal(page.ids.inspector.classList.contains('sheet'), true, 'the sheet is open on the answer being read');
  assert.equal(page.ids.scrim.hidden, false);
  page.doc.blurred = true;
  const before = page.focused();
  send(action('leak-an-iban'));
  await settle();
  assert.equal(page.ids.inspector.classList.contains('sheet'), false, 'closed');
  assert.equal(page.ids.scrim.hidden, true);
  assert.equal(page.ids.rail.hasAttribute('inert'), false, 'and the page is usable again');
  assert.notEqual(state.selected.assistant, read, 'the answer of the new command is the one selected');
  assert.match(text(page.ids.conversation), /answer to leak-an-iban/);
  assert.ok(page.focused() === before, 'the focus did not move');
  // with no sheet open, nothing changes
  send(action('inject-a-prompt'));
  await settle();
  assert.match(text(page.ids.conversation), /answer to inject-a-prompt/);
});

test('an id is 64 characters at most: a longer one is not an id the Lab UI could have drawn, and is not acted on or told', async () => {
  fresh();
  const long = `a${'b'.repeat(63)}`;
  assert.equal(actionOf({ source: lab, origin: LAB_ORIGINS[0], data: action(long) }), long);
  send(action(`${long}c`));
  await settle();
  assert.equal(actionOf({ source: lab, origin: LAB_ORIGINS[0], data: action(`${long}c`) }), null);
  assert.equal(toasts(), '');
});

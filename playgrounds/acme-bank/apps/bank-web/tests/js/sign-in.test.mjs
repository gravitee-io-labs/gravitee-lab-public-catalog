/* Signing in at Access Management's own login page, from the page's side: the window that is opened from a click on a person and that tells the page how the sign-in
   ended, what the page believes of it (only its own window, from its own origin) and what it does with it (asks the server who is signed in), choosing somebody who is
   signed in (no window), and the commands, which sign nobody in: one for somebody who is signed in asks as them, one for somebody who is not goes as it is, with no token,
   and the gateway's refusal is the answer. Over a small DOM, the real modules and a fetch that answers what the app would. */
import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

import { flush, installDom, text } from './dom-stub.mjs';

const IDS = ['rail', 'shell', 'conversation', 'message', 'send', 'announcer', 'toasts', 'open-tokens', 'composer', 'inspector', 'behind', 'behind-subject', 'behind-body',
  'monitor', 'team-monitor', 'team-feed', 'team-button', 'team-name', 'team-menu', 'team-picker', 'team-budget', 'team-short', 'team-long', 'team-triple',
  'money-form', 'money-from', 'money-to', 'money-amount', 'money-ref', 'money-send', 'behind-title', 'behind-close', 'scrim', 'person', 'person-button', 'person-menu',
  'person-name', 'person-role', 'person-avatar'];
const page = installDom({ ids: IDS, media: { '(max-width: 639px)': false, '(min-width: 1280px)': true } });
mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: 1_000_000 });
globalThis.location.origin = 'http://localhost:8110';
page.ids.rail.tabIndex = -1;
page.ids['team-menu'].hidden = true;
page.ids['team-picker'].append(page.ids['team-button'], page.ids['team-menu']);
page.ids.message.tag = 'textarea';
page.ids.scrim.hidden = true;
page.ids['behind-close'].tag = 'button';
page.ids['behind-close'].hidden = true;
page.ids['person-menu'].hidden = true;
page.ids.person.append(page.ids['person-button'], page.ids['person-menu']);
for (const id of ['person-button', 'open-tokens']) page.ids[id].tag = 'button';

const { bus, h } = await import('../../static/js/dom.js');
const store = await import('../../static/js/store.js');
const session = await import('../../static/js/session.js');
const chat = await import('../../static/js/chat.js');
const teams = await import('../../static/js/teams.js');
const money = await import('../../static/js/money.js');
const commands = await import('../../static/js/commands.js');
const { signInWindow } = await import('../../static/js/sign-in.js');
const done = await import('../../static/js/sign-in-done.js');
const { SIGN_IN, SIGN_IN_MESSAGE, SIGN_IN_WINDOW } = await import('../../static/js/words.js');
const { initAsking } = await import('../../static/js/asking.js');
const { state } = store;

const ORIGIN = 'http://localhost:8110';
const PEOPLE = {
  alice: { id: 'alice', name: 'Alice Martin', role: 'customer', username: 'alice@acme-bank.test', password: 'pw', send: { from: 'ACC-1001', to: 'ACC-2001', amount: 10 } },
  bob: { id: 'bob', name: 'Bob Chen', role: 'customer', username: 'bob@acme-bank.test', password: 'pw', send: { from: 'ACC-2001', to: 'ACC-1001', amount: 5 } },
  tina: { id: 'tina', name: 'Tina Torres', role: 'teller', username: 'tina@acme-bank.test', password: 'pw', send: { from: 'ACC-9', to: 'ACC-8', amount: 1 } },
};
const command = (id, label, persona, kind = 'chat', extra = {}) => ({ id, label, kind, persona, message: `question of ${id}`, transfer: null, team: '', direct: false, ...extra });
const GROUPS = [
  { id: 1, title: 'See everything', commands: [command('ask-ace-accounts', 'Ask Ace about my accounts', 'alice')] },
  { id: 3, title: 'Protect the tools', commands: [command('freeze-card-teller', 'Freeze a card as a teller', 'tina')] },
  { id: 4, title: 'Decide who may do what', commands: [command('read-other-accounts', 'Read another customer\'s accounts', 'bob'),
    command('move-600-yourself', 'Move EUR 600 yourself', 'bob', 'money', { transfer: { from_account: 'ACC-2001', to_account: 'ACC-1001', amount: 600 } })] },
];
const HOP = { kind: 'a2a', name: '', title: 'Bob asked Ace', system: 'A2A proxy', direct: false, outcome: 'ok', tone: 'ok', word: 'Answered', status: 200, ms: 100, summary: 'Ace answered.', facts: [], evidence: [] };

/* The server: who is signed in (the page learns it from the server, never from a message), and what was asked of it. */
const asked = [];
const server = { persona: 'alice', signed: ['alice'], signsInAs: null };
const who = () => ({ persona: server.persona, name: server.persona && PEOPLE[server.persona].name, role: server.persona && PEOPLE[server.persona].role, signed: [...server.signed] });
globalThis.fetch = async (path, options = {}) => {
  const body = options.body ? JSON.parse(options.body) : null;
  const method = options.method || 'GET';
  asked.push(`${method} ${path}`);
  let out = { error: 'no route' };
  let status = 404;
  if (path === '/api/session' && method === 'GET') [out, status] = [who(), 200];
  else if (path === '/api/session' && method === 'DELETE') { Object.assign(server, { persona: null, signed: [] }); [out, status] = [who(), 200]; }
  else if (path === '/api/session') {
    if (server.signed.includes(body.persona)) { server.persona = body.persona; [out, status] = [who(), 200]; } else [out, status] = [{ error: `${body.persona} is not signed in.`, who: who() }, 401];
  } else if (path.startsWith('/api/commands/')) {
    const run = GROUPS.flatMap((group) => group.commands).find((one) => path === `/api/commands/${one.id}/run`);
    const nobody = { ...HOP, title: 'Someone not signed in asked Ace', outcome: 'unauthorized', tone: 'deny', word: 'Unauthorized', status: 401, summary: 'Unauthorized: no token was sent' };
    if (run && !server.signed.includes(run.persona) && run.kind === 'money') {
      [out, status] = [{ ...nobody, kind: 'tool', title: 'Someone not signed in called transfer_funds', system: 'MCP proxy', protected: true, who: who() }, 200];       // a payment the gateway refuses is a receipt that says it did not move
    } else if (run && !server.signed.includes(run.persona)) {
      [out, status] = [{ error: 'The gateway refused the question: it asks for a token, and none was sent.', who: who(), rows: [nobody] }, 401];
    } else if (run) { server.persona = run.persona; [out, status] = [{ answer: `answer to ${run.id}`, gateway: 'on', protected: true, ms: 120, rows: [HOP], who: who() }, 200]; }
  }
  return { ok: status < 400, status, json: async () => out };
};

state.personas = Object.values(PEOPLE);
state.groups = GROUPS;
chat.initChat();
teams.initTeams();
money.initMoney();
commands.initCommands();
initAsking();
session.adopt(who());

/* The browser: the windows `window.open` makes, and the page's own origin. A window is where the login page would be. */
const opened = [];
let blocked = false;
globalThis.window.open = (url, name, features) => {
  if (blocked) return null;
  const popup = { url, name, features, closed: false, focused: 0, focus() { this.focused += 1; } };
  opened.push(popup);
  return popup;
};
const tell = (popup, outcome, extra = {}) => page.fire('window', 'message', { source: popup, origin: ORIGIN, data: { type: SIGN_IN_MESSAGE, outcome }, ...extra });
const toasts = () => text(page.ids.toasts);
const button = (id) => page.ids.rail.querySelector(`[data-key="${id}"]`);
async function settle() {
  for (let round = 0; round < 12; round += 1) {
    await flush();
    mock.timers.tick(60);
  }
}
function fresh({ persona = 'alice', signed = ['alice'] } = {}) {
  Object.assign(server, { persona, signed: [...signed] });
  session.adopt(who());
  state.running = null;
  state.gateway = true;
  bus.emit('conversation-reset');
  page.ids.toasts.replaceChildren();
  page.doc.blurred = false;
  asked.length = 0;
  opened.length = 0;
  blocked = false;
}

/* ---- the window ------------------------------------------------------------------------------------------------------------------ */

test('the login page is opened in a window named for it, for the person asked, from the click, and the window is brought forward', async () => {
  fresh();
  const finished = signInWindow('bob');
  assert.equal(opened.length, 1, 'opened at once, in the task of the click: nothing was awaited');
  assert.equal(opened[0].url, '/login?persona=bob');
  assert.match(opened[0].name, /^acme-bank-sign-in-[a-z0-9]{4,}$/);
  assert.match(opened[0].features, /^popup,width=\d+,height=\d+$/);
  assert.equal(opened[0].focused, 1);
  tell(opened[0], 'signed-in');
  assert.deepEqual(await finished, { ok: true, outcome: 'signed-in' });
});

test('a second tab of the app has a window of its own: the name is the page\'s, not the app\'s', async () => {
  fresh();
  const first = signInWindow('bob');
  const [popup] = opened;
  tell(popup, 'signed-in');
  await first;
  const other = await import('../../static/js/sign-in.js?another-tab');
  const second = other.signInWindow('bob');
  assert.notEqual(opened[1].name, popup.name, 'two tabs, two windows: the second tab does not take the first one\'s login page');
  tell(opened[1], 'signed-in');
  await second;
});

test('the page believes its own window and no other: another window, another origin, a message of another shape are not heard', async () => {
  fresh();
  const finished = signInWindow('bob');
  const [popup] = opened;
  const other = { closed: false };
  const forged = [
    { source: other, origin: ORIGIN }, { source: globalThis.window, origin: ORIGIN }, { source: null, origin: ORIGIN }, { source: undefined, origin: ORIGIN },
    { source: popup, origin: 'http://localhost:9000' }, { source: popup, origin: 'http://evil.example' }, { source: popup, origin: 'null' }, { source: popup, origin: '' },
    { source: popup, origin: 'http://localhost:8110.evil.example' }, { source: popup, origin: ORIGIN, data: null }, { source: popup, origin: ORIGIN, data: 'acme-bank:sign-in' },
    { source: popup, origin: ORIGIN, data: {} }, { source: popup, origin: ORIGIN, data: { type: 'gravitee-lab:action', id: 'x' } }, { source: popup, origin: ORIGIN, data: { type: 'acme-bank:Sign-in' } },
  ];
  let settled = false;
  finished.then(() => { settled = true; });
  for (const one of forged) page.fire('window', 'message', { data: { type: SIGN_IN_MESSAGE, outcome: 'signed-in' }, ...one });
  await flush();
  assert.equal(settled, false, 'none of them ended the sign-in');
  tell(popup, 'signed-in');
  assert.equal((await finished).ok, true);
});

test('an outcome the page has no sentence for is a failure, and one that is only the window\'s own words is not an outcome', async () => {
  for (const outcome of ['nonsense', 'blocked', 'closed', '__proto__', 'constructor', 5, null, undefined, ['signed-in']]) {
    fresh();
    const finished = signInWindow('bob');
    tell(opened[0], outcome);
    assert.deepEqual(await finished, { ok: false, outcome: 'failed' }, String(outcome));
  }
});

test('every outcome the server can send is a sentence the page can say, and the sentences of the window\'s own are another list', () => {
  assert.deepEqual(Object.keys(SIGN_IN), ['signed-in', 'refused', 'expired', 'other', 'stranger', 'failed']);
  assert.deepEqual(Object.keys(SIGN_IN_WINDOW), ['blocked', 'closed']);
  for (const sentence of [...Object.values(SIGN_IN), ...Object.values(SIGN_IN_WINDOW)]) assert.match(sentence, /^[A-Z].*\.$/);
});

test('a browser that does not open the window is told so, plainly, and nothing waits', async () => {
  fresh();
  blocked = true;
  assert.deepEqual(await signInWindow('bob'), { ok: false, outcome: 'blocked' });
});

test('a window the person closes ends the sign-in, but not before the page has looked twice: a window that closes itself has told the page first', async () => {
  fresh();
  const finished = signInWindow('bob');
  let ended = false;
  finished.then(() => { ended = true; });
  opened[0].closed = true;
  mock.timers.tick(500);
  await flush();
  assert.equal(ended, false, 'once is not enough');
  mock.timers.tick(500);
  assert.deepEqual(await finished, { ok: false, outcome: 'closed' });
  const again = signInWindow('bob');
  opened[1].closed = true;
  mock.timers.tick(500);
  tell(opened[1], 'signed-in');                                   // the window said it before the second look
  assert.deepEqual(await again, { ok: true, outcome: 'signed-in' });
});

test('a second sign-in goes to the same window and ends the first one; once a sign-in is over its window is not listened to', async () => {
  fresh();
  const first = signInWindow('bob');
  const second = signInWindow('tina');
  assert.deepEqual(await first, { ok: false, outcome: 'replaced' });
  assert.equal(opened[0].name, opened[1].name, 'a named window: the browser reuses it');
  tell(opened[1], 'signed-in');
  assert.equal((await second).ok, true);
  const listeners = globalThis.window.listeners.message.length;
  tell(opened[1], 'signed-in');
  assert.equal(globalThis.window.listeners.message.length, listeners, 'nothing is added by a message that nobody waits for');
});

/* ---- the small page the window ends on --------------------------------------------------------------------------------------------- */

test('the window tells its opener how it ended, to the page\'s own origin and no other, and closes itself', () => {
  for (const [outcome, search] of [['signed-in', '?outcome=signed-in'], ['refused', '?outcome=refused'], ['stranger', '?outcome=stranger']]) {
    const sent = [];
    const actions = [];
    const label = { textContent: '' };
    const result = done.finish({ search, origin: ORIGIN, opener: { postMessage: (message, origin) => sent.push({ message, origin }) }, clean: () => actions.push('clean'), close: () => actions.push('close') }, label);
    assert.equal(result, outcome);
    assert.deepEqual(sent, [{ message: { type: SIGN_IN_MESSAGE, outcome }, origin: ORIGIN }], 'nothing but the outcome, to the one origin');
    assert.deepEqual(actions, ['clean', 'close']);
    assert.equal(label.textContent, SIGN_IN[outcome]);
  }
});

test('an address that says nothing the page knows is a failure, and a window nothing opened stays and says how it ended', () => {
  for (const search of ['', '?outcome=', '?outcome=nonsense', '?outcome=__proto__', '?outcome=blocked', '?outcome[]=signed-in', '?code=abc&state=xyz']) {
    assert.equal(done.outcomeOf(search), 'failed', search);
  }
  assert.equal(done.outcomeOf('?outcome=signed-in&code=ignored'), 'signed-in');
  const actions = [];
  const label = { textContent: '' };
  done.finish({ search: '?outcome=failed', origin: ORIGIN, opener: null, clean: () => actions.push('clean'), close: () => actions.push('close') }, label);
  assert.deepEqual(actions, ['clean'], 'the address is cleaned, and the window is not closed: there is nobody to tell and the person reads it');
  assert.equal(label.textContent, 'Access Management did not answer. Try again in a minute.');
});

/* ---- choosing ------------------------------------------------------------------------------------------------------------------------ */

test('somebody who is signed in is chosen with no window: one request, the conversation starts again with them', async () => {
  fresh({ persona: 'alice', signed: ['alice', 'bob'] });
  const before = state.conversation;
  assert.equal(await session.choose('bob'), true);
  assert.deepEqual(asked, ['POST /api/session']);
  assert.equal(opened.length, 0);
  assert.equal(state.persona.id, 'bob');
  assert.equal(state.conversation > before, true, 'a new conversation');
});

test('somebody who is not signed in opens the login page; when the window says it is done the server is asked who is signed in, and only then do they ask', async () => {
  fresh();
  const choosing = session.choose('bob');
  assert.deepEqual([opened.length, asked], [1, []], 'the window first, in the click, and nothing asked of the server yet');
  assert.equal(state.persona.id, 'alice', 'nothing changes until the sign-in is over');
  Object.assign(server, { persona: 'bob', signed: ['alice', 'bob'] });            // the server finished the sign-in at /callback
  tell(opened[0], 'signed-in');
  assert.equal(await choosing, true);
  assert.deepEqual(asked, ['GET /api/session'], 'the message is told, not believed');
  assert.equal(state.persona.id, 'bob');
  assert.deepEqual(state.signed, ['alice', 'bob']);
});

test('a window that says it is done when the server is not is not believed', async () => {
  fresh();
  const choosing = session.choose('bob');
  tell(opened[0], 'signed-in');                                                    // a message, with the server holding nothing of Bob
  assert.equal(await choosing, false);
  assert.equal(state.persona.id, 'alice');
  assert.equal(toasts(), SIGN_IN.expired);
});

test('every way a sign-in can end without a person is said, in the words of the page: blocked, closed, refused, another person, a stranger, no answer', async () => {
  for (const [outcome, said, tone] of [['refused', SIGN_IN.refused, 'error'], ['expired', SIGN_IN.expired, 'error'], ['other', SIGN_IN.other, 'error'], ['stranger', SIGN_IN.stranger, 'error'],
    ['failed', SIGN_IN.failed, 'error']]) {
    fresh();
    const choosing = session.choose('bob');
    tell(opened[0], outcome);
    assert.equal(await choosing, false, outcome);
    assert.equal(toasts(), said, outcome);
    assert.equal(page.ids.toasts.querySelectorAll(`.toast.${tone}`).length, 1);
    assert.equal(state.persona.id, 'alice');
  }
  fresh();
  blocked = true;
  assert.equal(await session.choose('bob'), false);
  assert.equal(toasts(), SIGN_IN_WINDOW.blocked);
  fresh();
  const choosing = session.choose('bob');
  opened[0].closed = true;
  mock.timers.tick(1000);
  assert.equal(await choosing, false);
  assert.equal(toasts(), SIGN_IN_WINDOW.closed);
  assert.equal(page.ids.toasts.querySelectorAll('.toast.info').length, 1, 'closing a window is not an error');
});

test('where the person chose from the menu and the browser blocked the window, a plain message says so and nothing is pending', async () => {
  fresh();
  blocked = true;
  assert.equal(await session.choose('bob'), false);
  assert.equal(toasts(), SIGN_IN_WINDOW.blocked);
  assert.equal(page.ids.toasts.querySelectorAll('.toast.error').length, 1);
  assert.equal(page.ids.conversation.querySelector('.msg.problem'), null, 'a message in a corner, with no button: the person chooses again');
  assert.deepEqual(asked, []);
});

test('choosing the person who asks already changes nothing: the conversation stays, no window, no call', async () => {
  fresh();
  state.persona = PEOPLE.alice;
  bus.emit('conversation-reset');
  page.ids.conversation.append(h('div', { class: 'msg user' }, 'a question'));
  asked.length = 0;
  assert.equal(await session.choose('alice'), true);
  assert.deepEqual([asked, opened.length, page.ids.conversation.querySelectorAll('.msg.user').length], [[], 0, 1]);
});

/* ---- a command: the person's token if the app holds one, none if it does not, and never a sign-in ------------------------------------ */

test('a command for somebody who is signed in already asks as them with no window at all, whoever asked before', async () => {
  fresh({ persona: 'alice', signed: ['alice', 'tina'] });
  button('freeze-card-teller').click();
  await settle();
  assert.deepEqual(asked, ['POST /api/session', 'POST /api/commands/freeze-card-teller/run']);
  assert.equal(opened.length, 0);
  assert.equal(state.persona.id, 'tina');
  assert.match(text(page.ids.conversation), /answer to freeze-card-teller/);
});

test('a command for somebody who is not signed in is sent as it is: no window, no sign-in, no switch of person, and the gateway\'s refusal is the answer, with its hop (the A2A proxy, 401) selected', async () => {
  fresh({ persona: 'alice', signed: ['alice'] });
  button('read-other-accounts').click();
  assert.equal(opened.length, 0, 'nothing opens in the click: a command signs nobody in');
  await settle();
  assert.deepEqual(asked, ['POST /api/commands/read-other-accounts/run'], 'one request: no GET of the session to go on with, no switch to Bob');
  assert.equal(opened.length, 0);
  const problem = page.ids.conversation.querySelector('.msg.problem');
  assert.match(text(problem), /The gateway refused the question: it asks for a token, and none was sent\./);
  assert.equal(page.ids.conversation.querySelectorAll('.msg.user').length, 1, 'the question is there, as a bubble');
  const subject = state.turns.get(state.selected.assistant);
  assert.equal(subject.kind, 'failed');
  assert.deepEqual([subject.rows[0].title, subject.rows[0].system, subject.rows[0].status], ['Someone not signed in asked Ace', 'A2A proxy', 401]);
  assert.equal(state.persona.id, 'alice', 'Alice is signed in, and still asks');
  assert.deepEqual(state.signed, ['alice']);
  assert.deepEqual(problem.querySelectorAll('.btn').map((one) => text(one)), ['Choose who is asking'], 'a 401 is somebody who is not signed in: the way on is the person control, not the same command again');
  assert.equal(state.running, null);
  assert.equal(store.isBusy(), false);
  assert.equal(button('read-other-accounts').getAttribute('aria-disabled'), null, 'the rail is free');
  assert.equal(toasts(), '', 'nothing is said in a corner: the conversation says it');
});

test('with nobody signed in the refusal offers the way on, which is the person control: the same button is the refusal first and the answer once Alice has signed in', async () => {
  fresh({ persona: null, signed: [] });
  button('ask-ace-accounts').click();
  await settle();
  assert.deepEqual([asked, opened.length], [['POST /api/commands/ask-ace-accounts/run'], 0]);
  const problem = page.ids.conversation.querySelector('.msg.problem');
  assert.match(text(problem), /The gateway refused the question/);
  assert.deepEqual(problem.querySelectorAll('.btn').map((one) => text(one)), ['Choose who is asking'], 'the way on is the menu of who is asking');
  assert.equal(state.persona, null, 'nobody was signed in, nobody is');
  problem.querySelector('.btn').click();                                                               // the person control: the one place a person signs in
  assert.equal(page.ids['person-menu'].hidden, false, 'the button opens the menu of who is asking, and the click that opened it does not close it again (it reaches the document, where a click outside the menu closes it)');
  page.ids['person-menu'].querySelectorAll('.menu-item')[0].click();                                  // Alice
  assert.equal(opened.length, 1, 'the window opens from that click');
  assert.equal(opened[0].url, '/login?persona=alice');
  Object.assign(server, { persona: 'alice', signed: ['alice'] });
  tell(opened[0], 'signed-in');
  await settle();
  assert.equal(state.persona.id, 'alice');
  asked.length = 0;
  button('ask-ace-accounts').click();                                                                  // the same button
  await settle();
  assert.deepEqual([asked, opened.length], [['POST /api/commands/ask-ace-accounts/run'], 1]);
  assert.match(text(page.ids.conversation), /answer to ask-ace-accounts/);
  assert.equal(state.turns.get(state.selected.assistant).kind, 'chat');
});

test('a payment for somebody who is not signed in is refused by the gateway the same way: a receipt that says Not moved, with its hop selected, and no window', async () => {
  fresh({ persona: null, signed: [] });
  button('move-600-yourself').click();
  await settle();
  assert.deepEqual([asked, opened.length], [['POST /api/commands/move-600-yourself/run'], 0]);
  const receipt = page.ids.conversation.querySelector('.msg.pay');
  assert.match(text(receipt), /EUR 600 from ACC-2001 to ACC-1001/);
  assert.match(text(receipt), /Not moved/);
  const subject = state.turns.get(state.selected.assistant);
  assert.deepEqual([subject.kind, subject.rows[0].title, subject.rows[0].system, subject.rows[0].status], ['payment', 'Someone not signed in called transfer_funds', 'MCP proxy', 401]);
  assert.equal(state.running, null);
  assert.equal(store.isBusy(), false);
});

test('no command opens the sign-in window, whoever is signed in and whatever the browser does with a window: it is the person control\'s alone', async () => {
  for (const signed of [[], ['alice'], ['alice', 'bob', 'tina']]) {
    fresh({ persona: signed[0] || null, signed });
    blocked = false;
    for (const group of GROUPS) {
      for (const one of group.commands) {
        button(one.id).click();
        await settle();
      }
    }
    assert.equal(opened.length, 0, `signed in: ${signed.join(', ') || 'nobody'}`);
    assert.equal(page.ids.conversation.querySelectorAll('.msg.problem .btn').filter((one) => /^Sign in as/.test(text(one))).length, 0, 'no button of a message that signs somebody in');
    assert.equal(toasts().includes(SIGN_IN_WINDOW.blocked), false);
    assert.equal(state.running, null);
  }
});

test('a person the page believed signed in and the server does not hold (a sign-in that ended) is told, the page follows the server, and the command goes as it is: refused, with no token', async () => {
  fresh();
  state.signed = ['alice', 'bob'];                                                // the page believes Bob is signed in; the server holds only Alice
  button('read-other-accounts').click();
  await settle();
  assert.deepEqual(asked, ['POST /api/session', 'POST /api/commands/read-other-accounts/run'], 'the switch was refused, and the command was sent: with no token');
  assert.deepEqual(state.signed, ['alice'], 'what the server says');
  assert.equal(opened.length, 0);
  assert.match(text(page.ids.conversation.querySelector('.msg.problem')), /The gateway refused the question/);
  assert.equal(state.running, null);
});

test('a command the server refuses because another tab ended the sign-in is said in the conversation, with the server\'s own list of who is signed in', async () => {
  fresh();
  state.persona = PEOPLE.bob;                                                     // the page asks as Bob and believes Bob is signed in; the server holds only Alice
  state.signed = ['alice', 'bob'];
  await session.askAs('bob');
  asked.length = 0;
  button('read-other-accounts').click();
  await settle();
  assert.equal(asked.at(-1), 'POST /api/commands/read-other-accounts/run');
  assert.deepEqual(state.signed, ['alice']);
  assert.equal(state.persona.id, 'alice', 'the server says who asks: Alice');
  assert.match(text(page.ids.conversation.querySelector('.msg.problem')), /The gateway refused the question/);
});

test('asking as a person who is not signed in does nothing: no window, no call, nobody chosen', async () => {
  fresh();
  await session.askAs('bob');
  assert.deepEqual([asked, opened.length, state.persona.id], [[], 0, 'alice']);
  await session.askAs('alice');
  assert.deepEqual([asked, opened.length, state.persona.id], [[], 0, 'alice'], 'and for the person who asks already');
});

/* ---- signing out ------------------------------------------------------------------------------------------------------------------------- */

test('signing out forgets the tokens here, starts a new conversation, and says that Access Management keeps its own session', async () => {
  fresh({ persona: 'alice', signed: ['alice', 'bob'] });
  await session.signOut();
  assert.deepEqual(asked, ['DELETE /api/session']);
  assert.deepEqual([state.persona, state.signed], [null, []]);
  assert.equal(toasts(), 'Signed out of ACME Bank. Access Management keeps its own session.');
  assert.equal(page.ids.conversation.querySelectorAll('.msg').length, 0);
  const choosing = session.choose('alice');
  assert.equal(opened.length, 1, 'after a sign out the next choice is a sign-in, at the login page, whoever it is');
  tell(opened[0], 'refused');
  assert.equal(await choosing, false);
});

/* ---- the menu of who is asking ------------------------------------------------------------------------------------------------------ */

test('the menu says it signs in at Access Management, then each person with the user name and password of their account, each with its own copy button', () => {
  fresh();
  page.ids['person-button'].click();
  const menu = page.ids['person-menu'];
  assert.equal(text(menu.querySelector('.menu-label')), 'Sign in at Access Management');
  const people = menu.querySelectorAll('.menu-person');
  assert.deepEqual(people.map((one) => [text(one.querySelector('.menu-item .who span')), text(one.querySelector('.menu-item .who small'))]), [['Alice Martin', 'customer · signed in'], ['Bob Chen', 'customer'], ['Tina Torres', 'teller']],
    'the row of a person who is signed in says so: choosing them opens no window');
  assert.deepEqual(people.map((one) => one.querySelectorAll('.menu-cred').map((row) => [text(row.querySelector('.cred-what')), text(row.querySelector('code'))])), [
    [['username', 'alice@acme-bank.test'], ['password', 'pw']], [['username', 'bob@acme-bank.test'], ['password', 'pw']], [['username', 'tina@acme-bank.test'], ['password', 'pw']]]);
  assert.deepEqual(menu.querySelectorAll('.menu-copy').map((one) => one.getAttribute('aria-label')).slice(0, 2), ['Copy the username of Alice Martin', 'Copy the password of Alice Martin']);
  assert.equal(menu.querySelectorAll('.menu-copy').length, 6);
  assert.equal(menu.querySelectorAll('[aria-checked="true"]').length, 1, 'the one who asks');
  assert.equal(menu.querySelectorAll('button button').length, 0, 'a button is never inside a button');
  assert.deepEqual([...new Set(menu.querySelectorAll('.menu-copy').map((one) => one.getAttribute('role')))], ['menuitem'], 'a menu holds menu items: the copy buttons are ones');
  page.ids['person-button'].click();
});

test('a copy button copies its own text, says it, and leaves the menu open', async () => {
  fresh();
  const wrote = [];
  globalThis.navigator.clipboard = { writeText: async (value) => { wrote.push(value); } };
  page.ids['person-button'].click();
  const menu = page.ids['person-menu'];
  menu.querySelectorAll('.menu-copy')[2].click();                                   // Bob's user name
  await flush();
  assert.deepEqual(wrote, ['bob@acme-bank.test']);
  assert.equal(menu.querySelectorAll('.menu-copy')[2].classList.contains('done'), true);
  assert.equal(menu.hidden, false, 'the menu stays: the password is next');
  mock.timers.tick(2000);
  assert.equal(menu.querySelectorAll('.menu-copy')[2].classList.contains('done'), false);
  globalThis.navigator.clipboard = { writeText: async () => { throw new Error('not allowed here'); } };       // a frame that is not allowed the clipboard
  menu.querySelectorAll('.menu-copy')[3].click();
  await flush();
  assert.equal(menu.querySelectorAll('.menu-copy')[3].classList.contains('failed') || menu.querySelectorAll('.menu-copy')[3].classList.contains('done'), true);
  delete globalThis.navigator.clipboard;
  page.ids['person-button'].click();
});

test('the arrows of the menu move along the people and their copy buttons, and Sign out is there only for somebody who asks', () => {
  fresh();
  page.ids['person-button'].click();
  const menu = page.ids['person-menu'];
  const stops = () => menu.querySelectorAll('.menu-item, .menu-copy').map((one) => one.getAttribute('aria-label') || text(one));
  assert.equal(stops().length, 3 + 6 + 1);
  assert.equal(stops().at(-1), 'Sign out');
  page.ids['person-button'].click();
  fresh({ persona: null, signed: [] });
  page.ids['person-button'].click();
  assert.equal(menu.querySelectorAll('.menu-item').some((one) => /Sign out/.test(text(one))), false);
  page.ids['person-button'].click();
});

test('choosing a person in the menu is a sign-in for somebody who is not signed in, and instant for somebody who is', async () => {
  fresh({ persona: 'alice', signed: ['alice', 'tina'] });
  page.ids['person-button'].click();
  page.ids['person-menu'].querySelectorAll('.menu-item')[2].click();                // Tina: signed in
  await settle();
  assert.deepEqual([opened.length, state.persona.id], [0, 'tina']);
  page.ids['person-button'].click();
  page.ids['person-menu'].querySelectorAll('.menu-item')[1].click();                // Bob: not
  assert.equal(opened.length, 1, 'the window opens from the click on the person');
  tell(opened[0], 'refused');
  await settle();
  assert.equal(state.persona.id, 'tina');
});

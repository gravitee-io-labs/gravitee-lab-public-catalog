/* The commands over a small DOM: the list beside the conversation (every group of the guide's lessons and its buttons, always whole, with who each is for),
   what a click does (asks as the person, shows the answer where it belongs) and what it does not do: it signs nobody in and judges nothing. */
import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

import { flush, installDom, text } from './dom-stub.mjs';

const page = installDom({ ids: ['rail', 'shell', 'announcer', 'toasts', 'message'], media: { '(max-width: 639px)': false } });
mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: 1_000_000 });
page.ids.rail.tabIndex = -1;

const { bus } = await import('../../static/js/dom.js');
const { state, begin, isBusy } = await import('../../static/js/store.js');
const commands = await import('../../static/js/commands.js');

const command = (id, label, persona, kind = 'chat', extra = {}) => ({ id, label, kind, persona, message: 'x', transfer: null, team: '', direct: false, ...extra });
const GROUPS = [
  { id: 1, title: 'See everything', commands: [command('ask-ace-accounts', 'Ask Ace about my accounts', 'alice'), command('ask-ace-direct', 'Ask Ace without the gateway', 'alice', 'chat', { direct: true })] },
  { id: 2, title: 'Protect the model', commands: [command('leak-an-iban', 'Leak an IBAN', 'alice'), command('inject-a-prompt', 'Inject a prompt', 'alice')] },
  { id: 3, title: 'Protect the tools', commands: [command('freeze-card-customer', 'Freeze a card as a customer', 'alice'), command('freeze-card-teller', 'Freeze a card as a teller', 'tina')] },
  { id: 4, title: 'Decide who may do what', commands: [command('read-other-accounts', "Read another customer's accounts", 'bob')] },
  { id: 5, title: 'Cap what an agent may do', commands: [command('move-600-through-ace', 'Move EUR 600 through Ace', 'alice'), command('move-600-yourself', 'Move EUR 600 yourself', 'alice', 'money')] },
  { id: 6, title: 'Cap what teams spend', commands: [command('spend-hackathon-budget', 'Spend the Hackathon budget', null, 'budget', { team: 'team-hackathon' })] },
];
state.personas = [{ id: 'alice', name: 'Alice Martin' }, { id: 'bob', name: 'Bob Chen' }, { id: 'tina', name: 'Tina Torres' }];
state.groups = GROUPS;
commands.initCommands();

const rail = () => page.ids.rail;
const button = (id) => rail().querySelector(`[data-key="${id}"]`);

test('the rail is the list of commands, grouped under the titles of the guide, in order, with who each is for and nothing else but the bank over', () => {
  assert.equal(text(rail().querySelector('h2')), 'Commands');
  const groups = rail().querySelectorAll('.group');
  assert.deepEqual(groups.map((g) => text(g.querySelector('.group-title'))), ['1 See everything', '2 Protect the model', '3 Protect the tools', '4 Decide who may do what', '5 Cap what an agent may do', '6 Cap what teams spend']);
  assert.deepEqual(groups.map((g) => g.querySelectorAll('.command').map((b) => text(b.querySelector('.command-label')))), [
    ['Ask Ace about my accounts', 'Ask Ace without the gateway'], ['Leak an IBAN', 'Inject a prompt'], ['Freeze a card as a customer', 'Freeze a card as a teller'],
    ["Read another customer's accounts"], ['Move EUR 600 through Ace', 'Move EUR 600 yourself'], ['Spend the Hackathon budget']]);
  assert.deepEqual(rail().querySelectorAll('.command-who').map((w) => text(w)), ['Alice', 'Alice', 'Alice', 'Alice', 'Alice', 'Tina', 'Bob', 'Alice', 'Alice'],
    'one rule: a command for somebody says who, as a first name, whoever it is; the budget, which is a team\'s, says none');
  assert.equal(button('ask-ace-accounts').getAttribute('aria-label'), 'Ask Ace about my accounts, as Alice');
  assert.equal(button('leak-an-iban').getAttribute('aria-label'), 'Leak an IBAN, as Alice', 'a screen reader hears every name');
  assert.equal(rail().querySelectorAll('button').length, 10 + 1 + 1, 'ten commands, the control that collapses the rail and Start the bank over at the foot: nothing else is a control');
  assert.equal(text(rail().querySelector('.rail-foot button')), 'Start the bank over');
  assert.equal(button('freeze-card-teller').getAttribute('aria-label'), 'Freeze a card as a teller, as Tina');
  assert.equal(button('spend-hackathon-budget').getAttribute('aria-label'), 'Spend the Hackathon budget');
});

test('the list is always whole: no group opens or closes, nothing is folded, and every command can be run', () => {
  assert.equal(rail().querySelectorAll('[aria-expanded], details, summary').length, 0);
  assert.equal(rail().querySelectorAll('.command[aria-disabled]').length, 0, 'every command can be run');
  assert.equal(rail().querySelectorAll('h3').length, 6, 'a heading for each group: a screen reader moves from one to the next');
});

test('the rail has a collapse control, and a slim strip holds nothing but the control that shows it again', () => {
  assert.ok(rail().querySelector('.commands-head [data-key="edge"]'));
  state.railOpen = false;
  bus.emit('rail-state', false);
  assert.equal(rail().querySelectorAll('.command, h2, h3').length, 0);
  assert.equal(text(rail().querySelector('.strip-title')), 'Commands', 'the strip says what it holds');
  assert.equal(rail().querySelectorAll('button').length, 1);
  assert.equal(rail().querySelector('button').getAttribute('aria-label'), 'Show the commands');
  state.railOpen = true;
  bus.emit('rail-state', true);
  assert.equal(rail().querySelectorAll('.command').length, 10);
});

test('on a phone the commands are a tab of their own: no collapse control', () => {
  page.setMedia('(max-width: 639px)', true);
  assert.equal(rail().querySelector('.commands-head [data-key="edge"]'), null);
  assert.equal(rail().querySelectorAll('.command').length, 10);
  page.setMedia('(max-width: 639px)', false);
});

test('a change that touches nothing the rail shows does not draw it again: a hover and the screen reader\'s place stay', () => {
  const first = button('leak-an-iban');
  bus.emit('busy');
  bus.emit('commands');
  assert.equal(button('leak-an-iban'), first);
});

/* ---- a click --------------------------------------------------------------------------------------------------------------------- */

function ports(overrides = {}) {
  const calls = [];
  const emitted = [];
  const made = {
    state: { running: null }, isBusy: () => false, begin: () => () => {}, bus: { emit: (name, detail) => emitted.push([name, detail]) },
    toast: (message, tone) => calls.push(['toast', message, tone]),
    playChat: async (c) => { calls.push(['chat', c.id]); },
    playMoney: async (c) => { calls.push(['money', c.id]); },
    runBudget: async (c) => { calls.push(['budget', c.id]); },
    focusBack: (id) => calls.push(['focus', id]),
    ...overrides,
  };
  return { made, calls, emitted };
}

test('a command that asks Ace goes to the Assistant and asks; one that pays pays; the budget goes to Teams', async () => {
  for (const [c, view, how] of [[GROUPS[0].commands[0], 'assistant', 'chat'], [GROUPS[4].commands[1], 'assistant', 'money'], [GROUPS[5].commands[0], 'teams', 'budget']]) {
    const { made, calls, emitted } = ports();
    await commands.runCommand(c, made);
    assert.deepEqual(emitted.filter(([name]) => name === 'go'), [['go', view]], c.id);
    assert.deepEqual(calls.filter(([name]) => name !== 'focus'), [[how, c.id]]);
    assert.deepEqual(calls.at(-1), ['focus', c.id], 'the focus comes back to the command when it is over');
    assert.deepEqual(emitted.map(([name]) => name).filter((name) => name !== 'go'), ['running', 'running'], 'the rail is told it starts and ends');
    assert.equal(made.state.running, null);
  }
});

test('a command asks no question first and counts no wait: there is no dialog and no countdown in what it does', async () => {
  const { made, calls } = ports();
  await commands.runCommand(GROUPS[5].commands[0], made);
  assert.deepEqual(calls.map(([name]) => name), ['budget', 'focus']);
  assert.equal(page.doc.getElementById('confirm'), null);
});

test('a command that fails still ends the run and gives the focus back', async () => {
  const { made, calls } = ports({ playChat: async () => { throw new Error('boom'); } });
  await assert.rejects(commands.runCommand(GROUPS[0].commands[0], made), /boom/);
  assert.equal(made.state.running, null);
  assert.deepEqual(calls.at(-1), ['focus', 'ask-ace-accounts']);
});

test('while something runs a click says so and starts nothing', async () => {
  for (const busy of [{ isBusy: () => true }, { state: { running: 'leak-an-iban' } }]) {
    const { made, calls, emitted } = ports(busy);
    await commands.runCommand(GROUPS[0].commands[0], made);
    assert.deepEqual(calls, [['toast', 'Something is still running. Run it when it is done.', 'info']]);
    assert.deepEqual(emitted, []);
  }
});

test('the command being run says so, and the others wait without being disabled, so that the focus stays where the person put it; the rail is not drawn again', async () => {
  let release;
  const calls = [];
  const live = { state, isBusy, begin, bus, toast: () => {}, playChat: () => new Promise((resolve) => { release = resolve; }), playMoney: async () => {}, runBudget: async () => {},
    focusBack: (id) => calls.push(id) };
  const drawn = button('leak-an-iban');
  const running = commands.runCommand(GROUPS[1].commands[0], live);
  assert.equal(state.running, 'leak-an-iban');
  assert.equal(button('leak-an-iban'), drawn, 'written in place: the scroll of the rail and the pointer under it stay');
  assert.equal(button('leak-an-iban').getAttribute('aria-busy'), 'true');
  assert.ok(button('leak-an-iban').querySelector('.spinner'), 'a turning mark in place of the play mark');
  assert.equal(button('inject-a-prompt').getAttribute('aria-disabled'), 'true');
  assert.equal(button('inject-a-prompt').hasAttribute('disabled'), false);
  assert.equal(rail().querySelector('.rail-foot button').getAttribute('aria-disabled'), 'true', 'the bank is not started over in the middle of a run');
  release();
  await running;
  assert.equal(state.running, null);
  assert.equal(button('leak-an-iban'), drawn);
  assert.equal(button('leak-an-iban').getAttribute('aria-busy'), 'false');
  assert.equal(button('leak-an-iban').querySelector('.spinner'), null, 'the play mark is back');
  assert.ok(button('leak-an-iban').querySelector('svg'));
  assert.equal(button('inject-a-prompt').hasAttribute('aria-disabled'), false);
  assert.equal(rail().querySelector('.rail-foot button').hasAttribute('aria-disabled'), false);
  assert.deepEqual(calls, ['leak-an-iban']);
});

test('a click on a command of the rail runs it: while something runs it says so, which shows the button is wired to the run', () => {
  state.running = 'something';
  button('inject-a-prompt').click();
  assert.match(text(page.ids.toasts), /Something is still running\. Run it when it is done\./);
  assert.equal(state.running, 'something', 'and starts nothing');
  state.running = null;
  page.ids.toasts.replaceChildren();
});

/* ---- the foot, and the commands that could not be had ----------------------------------------------------------------------------- */

test('Start the bank over is a plain command: it asks nothing, and says what it did', async () => {
  const asked = [];
  globalThis.fetch = async (path, options = {}) => {
    asked.push(`${options.method || 'GET'} ${path}`);
    return { ok: true, status: 200, json: async () => ({ bank: { ok: true }, traffic: { ok: true } }) };
  };
  const heard = [];
  bus.on('bank-reset', (data) => heard.push(data));
  rail().querySelector('.rail-foot button').click();
  await flush();
  await flush();
  assert.deepEqual(asked, ['POST /api/presenter/reset']);
  assert.match(text(page.ids.toasts), /The bank starts over: balances and cards are back\./);
  assert.equal(heard.length, 1);
  assert.equal(page.doc.getElementById('confirm'), null);
});

test('the commands that cannot be had say so, with a button to ask again, and come back by themselves when the app answers', async () => {
  globalThis.fetch = async () => ({ ok: false, status: 0, json: async () => ({ error: 'x' }) });
  assert.equal(await commands.loadCommands(), false);
  assert.match(text(rail()), /The commands are not available/);
  assert.equal(rail().querySelectorAll('.command').length, 0);
  assert.ok(rail().querySelector('[data-key="reload"]'));
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ groups: GROUPS, budget_calls: 3 }) });
  page.fire('window', 'online');
  await flush();
  assert.equal(rail().querySelectorAll('.command').length, 10);
  assert.equal(state.budgetCalls, 3, 'how many answers the budget command asks for is the app\'s to say');
});

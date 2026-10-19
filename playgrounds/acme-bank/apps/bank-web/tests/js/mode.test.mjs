/* The two modes of the page. Framed by the Lab UI the Commands start as the slim strip, one click from open, because the guide has buttons that run them;
   standalone they are open (the router test holds that). What the person chose, by the edge control, is kept and wins in both. Run over a small DOM, the real
   router and the real rail. */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { installDom, text } from './dom-stub.mjs';

const page = installDom({ ids: ['shell', 'main', 'rail', 'inspector', 'toasts', 'announcer'], media: { '(max-width: 639px)': false, '(min-width: 1280px)': true } });
globalThis.window.parent = { postMessage() {} };                // framed by the Lab UI
page.ids.rail.tabIndex = -1;

const { state } = await import('../../static/js/store.js');
const { initRouter } = await import('../../static/js/router.js');
const commands = await import('../../static/js/commands.js');

const command = (id, label, persona) => ({ id, label, kind: 'chat', persona, message: 'x', transfer: null, team: '', direct: false });
state.personas = [{ id: 'alice', name: 'Alice Martin' }];
state.groups = [{ id: 1, title: 'See everything', commands: [command('ask-ace-accounts', 'Ask Ace about my accounts', 'alice')] },
  { id: 2, title: 'Protect the model', commands: [command('leak-an-iban', 'Leak an IBAN', 'alice'), command('inject-a-prompt', 'Inject a prompt', 'alice')] }];
commands.initCommands();                  // the page's own order: the rail, then the router, which decides whether it is open
initRouter();

const rail = () => page.ids.rail;
const edge = () => rail().querySelector('.rail-edge');

test('framed, with no choice of the person, the commands are the slim strip: it names what it holds and nothing else is there', () => {
  assert.equal(page.ids.shell.dataset.rail, 'closed');
  assert.equal(state.railOpen, false);
  assert.ok(rail().querySelector('.rail-strip'));
  assert.equal(text(rail().querySelector('.strip-title')), 'Commands');
  assert.equal(rail().querySelectorAll('.command').length, 0);
  assert.equal(rail().querySelectorAll('button').length, 1);
  assert.equal(edge().getAttribute('aria-label'), 'Show the commands');
  assert.deepEqual([page.stored['acme-bank.rail'], page.stored['acme-bank.rail-in-lab']], [undefined, undefined], 'a default is no choice: nothing is kept');
});

test('one click opens them, and that is the person\'s choice: it is kept, and the next visit finds them open', () => {
  edge().click();
  assert.equal(page.ids.shell.dataset.rail, 'open');
  assert.equal(rail().querySelectorAll('.command').length, 3);
  assert.equal(page.stored['acme-bank.rail-in-lab'], 'true', 'kept for the Lab UI');
  assert.equal(page.stored['acme-bank.rail'], undefined, 'and not as the choice of a tab of its own');
});

test('and one click closes them again, which is kept too', () => {
  edge().click();
  assert.equal(page.ids.shell.dataset.rail, 'closed');
  assert.equal(rail().querySelectorAll('.command').length, 0);
  assert.equal(page.stored['acme-bank.rail-in-lab'], 'false');
});

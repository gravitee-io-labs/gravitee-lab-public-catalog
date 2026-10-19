/* The notices and pieces every part of the page draws the same way, run over a small DOM: the announcer, the toasts, the evidence of a call, the links a
   model or a gateway wrote. */
import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

import { installDom, text } from './dom-stub.mjs';

const page = installDom({ ids: ['announcer', 'toasts'] });
mock.timers.enable({ apis: ['setTimeout'] });
const ui = await import('../../static/js/ui.js');
const { api } = await import('../../static/js/dom.js');

test('the announcer is emptied first, so that the same words said twice are heard twice, and says them a moment later', () => {
  ui.say('Ace answered');
  assert.equal(page.ids.announcer.textContent, '');
  mock.timers.tick(61);
  assert.equal(page.ids.announcer.textContent, 'Ace answered');
  ui.say('Ace answered');
  assert.equal(page.ids.announcer.textContent, '', 'cleared before it says it again');
  mock.timers.tick(61);
  assert.equal(page.ids.announcer.textContent, 'Ace answered');
});

test('three notices at most, an error stays until it is closed and is an alert, the others go by themselves and are announced', () => {
  const box = page.ids.toasts;
  box.replaceChildren();
  ui.toast('one');
  ui.toast('two');
  ui.toast('three');
  ui.toast('four');
  assert.deepEqual(box.children.map((t) => text(t.querySelector('.toast-text'))), ['two', 'three', 'four']);
  ui.toast('broke', 'error');
  const error = box.children[box.children.length - 1];
  assert.equal(error.getAttribute('role'), 'alert');
  assert.ok(error.querySelector('.toast-close'), 'closed by the person');
  mock.timers.tick(30_000);
  mock.timers.tick(300);                                              // a notice that goes first takes a moment to leave
  assert.ok(box.children.includes(error), 'an error does not go away by itself');
  assert.equal(box.children.some((t) => text(t.querySelector('.toast-text')) === 'four'), false, 'the others did');
  error.querySelector('.toast-close').click();
  mock.timers.tick(300);
  assert.equal(box.children.includes(error), false);
});

test('a notice stops while the pointer or the focus is on it', () => {
  const box = page.ids.toasts;
  box.replaceChildren();
  ui.toast('read me', 'ok', 1000);
  const item = box.firstChild;
  item.dispatchEvent(new Event('mouseenter'));
  mock.timers.tick(5000);
  assert.equal(box.children.length, 1, 'held while the pointer is on it');
  item.dispatchEvent(new Event('mouseleave'));
  mock.timers.tick(1100);
  mock.timers.tick(300);
  assert.equal(box.children.length, 0);
});

const evidence = (kind, extra = {}) => ({ kind, label: kind[0].toUpperCase() + kind.slice(1), url: `http://gamma.test/${kind}`, ...extra });

test('the evidence of a call is one row of buttons in a fixed order, all of one weight, and nothing is folded', () => {
  const row = ui.evidenceButtons([evidence('decisions'), evidence('spend'), evidence('logs'), evidence('trace')], 'Ace called list_accounts');
  assert.deepEqual(row.querySelectorAll('a.evidence').map((a) => text(a)), ['Trace', 'Logs', 'Decisions', 'Spend']);
  assert.equal(row.querySelectorAll('details').length, 0);
  assert.equal(row.getAttribute('role'), 'group');
  assert.equal(row.getAttribute('aria-label'), 'Evidence in Gamma, Ace called list_accounts', 'the group says which hop it is of');
  assert.equal(ui.evidenceButtons([], 'x'), null, 'nothing to show: no row');
  assert.equal(ui.evidenceButtons(undefined, 'x'), null);
  assert.deepEqual(ui.EVIDENCE_ORDER, ['trace', 'logs', 'decisions', 'spend']);
});

test('a link that is not into Gamma or the evidence route is not a link: the page never follows what a gateway wrote', () => {
  const row = ui.evidenceButtons([evidence('logs', { url: 'javascript:alert(1)' }), evidence('trace', { url: '//evil.example/x' }), evidence('decisions', { url: '/api/evidence?kind=decisions&api=mcp&request=r&at=1' }),
    evidence('spend', { url: '/api/trace?x=1' })], 'Ace called x');
  assert.deepEqual(row.querySelectorAll('a.evidence').map((a) => a.getAttribute('href')), ['/api/evidence?kind=decisions&api=mcp&request=r&at=1']);
  for (const a of row.querySelectorAll('a.evidence')) {
    assert.equal(a.getAttribute('rel'), 'noopener');
    assert.equal(a.getAttribute('target'), '_blank');
    assert.equal(a.hasAttribute('data-gamma'), true);
    assert.match(a.getAttribute('aria-label'), /opens Gamma/);
  }
  assert.equal(ui.evidenceButtons([evidence('logs', { url: 'javascript:alert(1)' })], 'x'), null, 'and with none left there is no row');
});

test('each button says which hop it is of and what it opens, on hover and to a screen reader: they are many on one screen', () => {
  const row = ui.evidenceButtons([evidence('trace'), evidence('logs'), evidence('decisions'), evidence('spend')], 'Ace called transfer_funds');
  const links = row.querySelectorAll('a.evidence');
  assert.deepEqual(links.map((a) => a.getAttribute('title')), ['The trace of this call, in Gamma', 'The log entry of this call, in Gamma',
    'The decision about this call, in Gamma', 'What the run spent, in Gamma']);
  assert.deepEqual(links.map((a) => a.getAttribute('aria-label')), ['Trace, Ace called transfer_funds (opens Gamma)', 'Logs, Ace called transfer_funds (opens Gamma)',
    'Decisions, Ace called transfer_funds (opens Gamma)', 'Spend, Ace called transfer_funds (opens Gamma)']);
  assert.deepEqual(links.map((a) => text(a)), ['Trace', 'Logs', 'Decisions', 'Spend'], 'the words on the buttons are the same');
  assert.equal(ui.evidenceTitle({ kind: 'surprise' }), null);
  assert.equal(ui.evidenceTitle({ kind: 'constructor' }), null, 'a kind that is a property of every object is no kind');
});

test('a hop title is text: set as an attribute, never as markup', () => {
  const row = ui.evidenceButtons([evidence('trace')], 'Ace called <b>x</b>');
  assert.equal(row.querySelector('a.evidence').getAttribute('aria-label'), 'Trace, Ace called <b>x</b> (opens Gamma)');
  assert.equal(row.querySelectorAll('b').length, 0);
});

test('a badge is a small label: its words, a mark of its own where the call did not go through, and the word a screen reader adds to a number', () => {
  const plain = ui.badge('system', 'MCP proxy');
  assert.equal(plain.getAttribute('class'), 'badge system');
  assert.equal(text(plain), 'MCP proxy');
  assert.equal(plain.querySelectorAll('svg').length, 0, 'no mark: nothing went wrong');
  const refused = ui.badge('status', '403', { tone: 'deny', word: 'Denied by policy', title: 'Denied by policy' });
  assert.equal(refused.getAttribute('class'), 'badge status deny');
  assert.equal(refused.getAttribute('title'), 'Denied by policy');
  assert.equal(refused.querySelectorAll('svg').length, 1, 'a mark beside the number: its color is not what says it');
  assert.equal(text(refused.querySelector('.sr')).trim(), 'Denied by policy');
  const ok = ui.badge('status', '200', { tone: null, word: 'Answered' });
  assert.equal(ok.getAttribute('class'), 'badge status');
  assert.equal(ok.querySelectorAll('svg').length, 0);
});

test('every call the page makes to the app carries the header the app asks for, and never throws', async () => {
  const seen = [];
  globalThis.fetch = async (path, options) => { seen.push({ path, options }); return { ok: true, status: 200, json: async () => ({ ok: 1 }) }; };
  await api('/api/personas');
  await api('/api/chat', { method: 'POST', body: { a: 1 } });
  assert.deepEqual(seen.map((s) => s.options.headers['X-Requested-With']), ['acme-bank', 'acme-bank']);
  assert.equal(seen[1].options.headers['Content-Type'], 'application/json');
  globalThis.fetch = async () => { throw new Error('down'); };
  const failed = await api('/api/personas');
  assert.deepEqual([failed.ok, failed.status], [false, 0]);
});

test('a link a model wrote shows where it leads, and only an http or https address is a link', () => {
  const node = ui.richText('See [Open in Gamma](https://evil.example/login) now, and [x](javascript:alert(1)).');
  const link = node.children.flatMap((p) => p.children).find((c) => c.tag === 'a');
  assert.equal(link.getAttribute('href'), 'https://evil.example/login');
  assert.match(text(link), /Open in Gamma .*evil\.example/, 'the label and the real host side by side');
  assert.equal(node.children.flatMap((p) => p.querySelectorAll('a')).length, 1);
  assert.equal(link.getAttribute('rel'), 'noopener');
});

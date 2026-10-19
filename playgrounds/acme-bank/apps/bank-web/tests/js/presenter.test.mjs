/* The Presenter over a small DOM: the check (its groups and the summary in words; nothing of the protections: the page does not read them), Models,
   Traffic (the button says the state) and Bank (what the reset gave). */
import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

import { installDom, text, flush } from './dom-stub.mjs';

const page = installDom({ ids: ['presenter-check', 'check-summary', 'check-list', 'presenter-warm', 'warm-list', 'presenter-traffic', 'traffic-state', 'presenter-reset', 'reset-list', 'announcer', 'toasts'] });
mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: 1_000_000 });
for (const id of ['presenter-check', 'presenter-warm', 'presenter-traffic', 'presenter-reset']) page.ids[id].tag = 'button';
page.ids['check-summary'].hidden = true;

const { bus } = await import('../../static/js/dom.js');
const { initPresenter } = await import('../../static/js/presenter.js');

const item = (extra) => ({ group: 'platform', status: 'ok', label: 'Gamma', detail: '', ms: 40, ...extra });
let routes = {};
const calls = [];
globalThis.fetch = async (path, options = {}) => {
  calls.push(`${options.method || 'GET'} ${path}`);
  const out = typeof routes[path] === 'function' ? routes[path]() : routes[path];
  const failed = out && out.fail;
  return { ok: !failed, status: failed || 200, json: async () => (failed ? out.body : out) };
};
const settle = async () => { await flush(); await flush(); mock.timers.tick(100); await flush(); };
const rows = () => page.ids['check-list'].querySelectorAll('li').map((li) => ({ cls: li.className, text: text(li) }));

initPresenter();

test('the check says each row where it was found, in its group, and the summary in words', async () => {
  routes = { '/api/presenter/check': { items: [item({ label: 'Gamma API' }), item({ label: 'Ace' }), item({ group: 'data', label: 'Accounts', detail: '4 accounts' })], ready: true, ms: 640 } };
  page.ids['presenter-check'].click();
  assert.equal(page.ids['presenter-check'].disabled, true, 'a button waits while its work runs');
  await settle();
  assert.equal(page.ids['presenter-check'].disabled, false);
  const got = rows();
  assert.deepEqual(got.filter((r) => r.cls.includes('group-label')).map((r) => r.text), ['Platform', 'Traffic and data']);
  assert.deepEqual(got.filter((r) => !r.cls.includes('group-label')).map((r) => r.text), ['Gamma API', 'Ace', 'Accounts4 accounts']);
  assert.equal(text(page.ids['check-summary']), 'Ready');
  assert.equal(page.ids['check-summary'].hidden, false);
  assert.equal(page.ids['check-summary'].className, 'chip ok');
  assert.equal(page.ids.announcer.textContent, 'Ready');
});

test('a check that found something to look at says how many, and one that found something wrong says it is not ready', async () => {
  routes = { '/api/presenter/check': { items: [item({ label: 'Ace', status: 'warn', detail: 'Slow', fix: 'Warm it up' }), item({ label: 'Mongo', status: 'warn', detail: 'Slow' })], ready: true, ms: 100 } };
  page.ids['presenter-check'].click();
  await settle();
  assert.equal(text(page.ids['check-summary']), 'Ready, 2 to check');
  assert.equal(page.ids['check-summary'].className, 'chip warn');
  assert.ok(rows().some((r) => r.text.includes('Warm it up')), 'what to do is on the row');
  routes = { '/api/presenter/check': { items: [item({ label: 'Gamma API', status: 'fail', detail: 'No answer', fix: 'Start the platform' })], ready: false, ms: 100 } };
  page.ids['presenter-check'].click();
  await settle();
  assert.equal(text(page.ids['check-summary']), 'Not ready');
  assert.equal(page.ids['check-summary'].className, 'chip fail');
  assert.equal(page.ids.announcer.textContent, 'Not ready');
});

test('a check the app could not run says so on the list and leaves no summary', async () => {
  routes = { '/api/presenter/check': { fail: 502, body: { error: 'The bank app could not be reached' } } };
  page.ids['presenter-check'].click();
  await settle();
  assert.equal(page.ids['check-summary'].hidden, true);
  assert.ok(rows()[0].cls.includes('fail'));
  assert.ok(rows()[0].text.includes('Reload the page'));
});

test('warming up shows each step as a row, and says what is going on while it runs', async () => {
  routes = { '/api/presenter/warmup': { steps: [{ label: 'Model', status: 'ok', detail: '' }, { label: 'Guard rails model', status: 'fail', detail: 'No answer' }] } };
  page.ids['presenter-warm'].click();
  assert.ok(text(page.ids['warm-list']).startsWith('Warming up the models'));
  await settle();
  const warm = page.ids['warm-list'].querySelectorAll('li');
  assert.deepEqual(warm.map((li) => li.className), ['check ok', 'check fail']);
  assert.ok(calls.includes('POST /api/presenter/warmup'));
});

test('the traffic button says what pressing it does, and a line says the state only when it is neither running nor paused', async () => {
  routes = { '/api/presenter/traffic': { paused: false, status: { state: 'running' } } };
  bus.emit('view', 'presenter');
  await settle();
  assert.equal(text(page.ids['presenter-traffic']), 'Pause traffic');
  assert.equal(page.ids['traffic-state'].textContent, '');
  routes = { '/api/presenter/traffic': { paused: false, status: { state: 'warming-up' } } };
  bus.emit('view', 'presenter');
  await settle();
  assert.equal(page.ids['traffic-state'].textContent, 'Warming up');
  routes = { '/api/presenter/traffic': { paused: true, status: { state: 'waiting' } } };
  bus.emit('view', 'presenter');
  await settle();
  assert.equal(text(page.ids['presenter-traffic']), 'Resume traffic');
  assert.equal(page.ids['traffic-state'].textContent, '', 'the button says it: paused');
  routes = { '/api/presenter/traffic': { paused: false, status: { state: 'running' } } };
  page.ids['presenter-traffic'].click();
  await settle();
  assert.ok(calls.includes('POST /api/presenter/traffic'));
  assert.equal(text(page.ids['presenter-traffic']), 'Pause traffic');
  assert.ok(text(page.ids.toasts).includes('Traffic resumed.'));
});

test('the traffic that cannot be read says why where its state is', async () => {
  routes = { '/api/presenter/traffic': { fail: 502, body: { error: 'The traffic generator is not answering' } } };
  bus.emit('view', 'presenter');
  await settle();
  assert.ok(page.ids['traffic-state'].textContent.length > 0);
});

test('starting the bank over lists what came back: the balances and cards, and the traffic counters', () => {
  bus.emit('bank-reset', { bank: { ok: true }, traffic: { ok: false, detail: 'No answer' } });
  const got = page.ids['reset-list'].querySelectorAll('li').map((li) => ({ cls: li.className, text: text(li) }));
  assert.deepEqual(got.map((r) => r.text.replace(/No answer/, '').trim()), ['Balances and cards', 'Traffic counters']);
  assert.ok(got[0].cls.includes('ok') && got[1].cls.includes('fail'));
});

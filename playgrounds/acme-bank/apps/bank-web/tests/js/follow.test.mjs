/* The page of a link of the evidence opened in a tab of its own: what it says while it looks, where it goes, and what it does when Gamma has none of it
   or does not answer. It looks for the item the way the app does inside the Lab UI, and its words are the app's. */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { flush, installDom, text } from './dom-stub.mjs';

const TRACE = 'http://gamma.test/environments/default/aim/observe/tracing/api-1/trace-9';
const LIST = 'http://gamma.test/environments/default/aim/observe/tracing/api-1?q=abc&v=1';
const SEARCH = '?kind=trace&api=a2a&request=req-12345678&at=1791504000000';
const asked = [];
let answers = [];
const page = installDom({ ids: ['follow-text'], fetch: async (path) => {
  asked.push(path);
  const answer = answers.length > 1 ? answers.shift() : answers[0];
  return { ok: answer !== null, status: answer === null ? 502 : 200, json: async () => answer };
} });
const spinner = page.el('follow-spinner', 'span');
spinner.hidden = true;
const retry = page.el('follow-retry', 'button');
retry.hidden = true;
const reloads = [];
globalThis.location.reload = () => reloads.push(1);
const { follow } = await import('../../static/js/follow.js');
const { BEAT } = await import('../../static/js/lookup.js');
const { EVIDENCE, GAMMA_DOWN, TRY_AGAIN } = await import('../../static/js/words.js');

const run = async (search, replies, { sleeps = [], clock = null } = {}) => {
  answers = replies;
  asked.length = 0;
  const went = [];
  const events = [];
  const result = await follow(search, {
    go: (url) => { went.push(url); events.push(`go:${text(page.ids['follow-text'])}`); },
    sleep: async (ms) => { sleeps.push(ms); events.push(`sleep:${ms}:${text(page.ids['follow-text'])}`); if (clock) clock.now += ms; },
    now: clock ? () => clock.now : Date.now,
  });
  return { went, events, result, said: text(page.ids['follow-text']) };
};

test('it says what it is looking for, in the words of the app, and goes to the item when it is there', async () => {
  for (const kind of ['trace', 'logs', 'decisions', 'spend']) {
    const out = await run(`?kind=${kind}&api=a2a&request=req-12345678&at=1`, [{ state: 'found', url: TRACE }]);
    assert.deepEqual(out.went, [TRACE], kind);
    assert.equal(out.said, EVIDENCE[kind].looking, 'what it was looking for is what it said');
    assert.equal(page.doc.title, EVIDENCE[kind].looking, 'and the tab says it');
    assert.equal(spinner.hidden, false, 'with its sign that it works');
    assert.equal(retry.hidden, true);
  }
  assert.deepEqual(asked, ['/api/evidence?kind=spend&api=a2a&request=req-12345678&at=1&resolve=1'], 'it asks the route of the app, once, for the item');
});

test('an item that Gamma has not got yet is asked for again by itself, and nobody has to press anything', async () => {
  const sleeps = [];
  const out = await run(SEARCH, [{ state: 'pending' }, { state: 'pending' }, { state: 'found', url: TRACE }], { sleeps });
  assert.deepEqual(sleeps, [1500, 1500]);
  assert.deepEqual(out.went, [TRACE]);
  assert.equal(asked.length, 3);
  assert.equal(out.said, EVIDENCE.trace.looking, 'and it still says what it looks for');
});

test('what Gamma has none of is said first, then the list that opens instead takes the tab, after a beat to read why', async () => {
  const sleeps = [];
  const out = await run(SEARCH, [{ state: 'missing', url: LIST }], { sleeps });
  assert.deepEqual(sleeps, [BEAT]);
  assert.deepEqual(out.events, [`sleep:${BEAT}:${EVIDENCE.trace.missing}`, `go:${EVIDENCE.trace.missing}`], 'the sentence is on the page before the list, and stays');
  assert.deepEqual(out.went, [LIST]);
});

test('Gamma that does not answer opens nothing, says so, and offers to try again (as the Lab UI does)', async () => {
  for (const reply of [{ state: 'down' }, null, 'junk', { state: 'surprise', url: TRACE }]) {
    reloads.length = 0;
    const out = await run(SEARCH, [reply]);
    assert.deepEqual(out.went, [], JSON.stringify(reply));
    assert.equal(out.said, GAMMA_DOWN);
    assert.equal(page.doc.title, GAMMA_DOWN);
    assert.equal(spinner.hidden, true, 'it is not looking any more');
    assert.equal(retry.hidden, false);
    assert.equal(text(retry), TRY_AGAIN);
    assert.equal(page.focused(), retry, 'the keyboard is where the way out is');
    retry.onclick();
    assert.deepEqual(reloads, [1], 'it looks again from the start');
  }
});

test('a lookup that Gamma keeps answering "not yet" ends on the same words, rather than going on for ever', async () => {
  const clock = { now: 0 };
  const out = await run(SEARCH, [{ state: 'pending' }], { clock });
  assert.deepEqual(out.went, []);
  assert.equal(out.said, GAMMA_DOWN);
});

test('it goes only to a page of Gamma: what the app says that is not one is down, and an address that is not a link of the evidence is not looked up at all', async () => {
  for (const url of ['/api/evidence?kind=trace', 'javascript:alert(1)', '//evil.example/x', 'data:text/html,x', null]) {
    const out = await run(SEARCH, [{ state: 'found', url }]);
    assert.deepEqual(out.went, [], String(url));
    assert.equal(out.said, GAMMA_DOWN);
  }
  for (const search of ['', undefined]) {
    const out = await run(search, [{ state: 'found', url: TRACE }]);
    assert.deepEqual([out.went, out.said, asked], [[], GAMMA_DOWN, []], `${search}: no address, nothing asked of the app`);
  }
  for (const search of ['?', '?x=1']) {
    const out = await run(search, [null]);              // the route refuses an address the page never makes (400)
    assert.deepEqual([out.went, out.said], [[], GAMMA_DOWN], search);
  }
  await flush();
});

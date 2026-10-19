/* Inside the Lab UI a way into Gamma does not open a browser tab: the page tells its parent where to go and does nothing else. Standalone it is a
   link like any other. A link a model wrote is never one of them. */
import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

import { Ev, flush, installDom, text } from './dom-stub.mjs';

const TRACE = 'http://gamma.test/environments/default/aim/observe/tracing/api-1/trace-9';
const asked = [];
let answer = { state: 'found', url: TRACE };
const page = installDom({ ids: ['toasts', 'announcer'], fetch: async (path) => {
  const lookup = path.startsWith('/api/evidence?');
  asked.push(path);
  return { ok: lookup, status: lookup ? 200 : 404, json: async () => (lookup ? answer : { error: 'no' }) };
} });
const { h } = await import('../../static/js/dom.js');
const { LAB_ORIGINS, embedded, initEmbed } = await import('../../static/js/embed.js');
const { BEAT, destination, isLookup, kindOf, wordsOf } = await import('../../static/js/lookup.js');
const { GAMMA_DOWN } = await import('../../static/js/words.js');
const EVIDENCE = '/api/evidence?kind=trace&api=a2a&request=req-12345678&at=1';

const sent = [];
const parent = { postMessage: (message, origin) => sent.push({ message, origin }) };
const link = (attrs) => { const a = h('a', { target: '_blank', rel: 'noopener', ...attrs }, 'x'); page.body.append(a); return a; };
globalThis.window.parent = globalThis.window;
initEmbed();

test('standalone a way into Gamma is a link that opens a new tab, and the page does nothing else', async () => {
  assert.equal(embedded(), false);
  const gamma = link({ href: 'http://gamma.test/x', 'data-gamma': '' });
  const event = new Ev('click', { target: gamma });
  page.doc.dispatchEvent(event);
  assert.equal(event.defaultPrevented, false);
  await flush();
  assert.deepEqual(sent, []);
});

test('framed, it posts {type, url} to the parent, takes the click and does nothing else', async () => {
  globalThis.window.parent = parent;
  assert.equal(embedded(), true);
  const gamma = link({ href: 'http://gamma.test/environments/default/aim/ai-workspaces/ws-1/spend', 'data-gamma': '' });
  const event = new Ev('click', { target: gamma });
  page.doc.dispatchEvent(event);
  await flush();
  assert.equal(event.defaultPrevented, true, 'no tab opens');
  assert.deepEqual([...new Set(sent.map((s) => JSON.stringify(s.message)))], [JSON.stringify({ type: 'gravitee-lab:open', url: 'http://gamma.test/environments/default/aim/ai-workspaces/ws-1/spend' })]);
  assert.deepEqual(sent.map((s) => s.origin), LAB_ORIGINS, 'the browser does not say who the parent is: the Lab UI\'s own origins, each of them, never any origin');
  assert.equal(sent.some((s) => s.origin === '*'), false);
  assert.deepEqual(Object.keys(sent[0].message), ['type', 'url'], 'nothing secret is sent: the address of a page of Gamma, and nothing else');
});

test('where the browser says who the parent is the message goes to that origin and to no other', async () => {
  sent.length = 0;
  globalThis.location.ancestorOrigins = ['http://localhost:9000'];
  page.doc.dispatchEvent(new Ev('click', { target: link({ href: 'http://gamma.test/x', 'data-gamma': '' }) }));
  await flush();
  assert.deepEqual(sent.map((s) => s.origin), ['http://localhost:9000']);
  sent.length = 0;
  delete globalThis.location.ancestorOrigins;
  page.doc.referrer = 'http://127.0.0.1:9000/playgrounds/acme-bank';
  page.doc.dispatchEvent(new Ev('click', { target: link({ href: 'http://gamma.test/x', 'data-gamma': '' }) }));
  await flush();
  assert.deepEqual(sent.map((s) => s.origin), ['http://127.0.0.1:9000'], 'the origin of the page that framed it');
  page.doc.referrer = '';
  sent.length = 0;
});

test('the evidence of a call is a route of this app that finds the item: it is asked where the item is, and the page of Gamma is what is posted', async () => {
  sent.length = 0;
  asked.length = 0;
  const trace = link({ href: EVIDENCE, 'data-gamma': '' });
  page.doc.dispatchEvent(new Ev('click', { target: trace }));
  assert.equal(trace.getAttribute('aria-busy'), 'true', 'it says it is looking while it does');
  page.doc.dispatchEvent(new Ev('click', { target: trace }));
  await flush();
  assert.deepEqual(sent.map((s) => s.message.url), LAB_ORIGINS.map(() => TRACE), 'one click is one lookup: the second, while it looked, was ignored');
  assert.deepEqual(asked, [`${EVIDENCE}&resolve=1`]);
  assert.equal(trace.getAttribute('aria-busy'), null);
  assert.deepEqual(await destination(EVIDENCE), { state: 'found', url: TRACE });
});

test('which evidence a link is, read from its address', () => {
  assert.equal(isLookup(EVIDENCE), true);
  assert.deepEqual(['trace', 'logs', 'decisions', 'spend'].map((kind) => kindOf(`/api/evidence?kind=${kind}&api=mcp&request=r&at=1`)), ['trace', 'logs', 'decisions', 'spend']);
  for (const other of ['http://gamma.test/x', '/api/trace?x=1', '/api/evidence', undefined, null, 5]) {
    assert.equal(isLookup(other), false, String(other));
    assert.equal(kindOf(other), null, String(other));
  }
});

test('an item Gamma has not got yet is asked for again by itself, and the page says it is looking only when it takes a moment', async () => {
  const sleeps = [];
  const states = [{ state: 'pending' }, { state: 'pending' }, { state: 'found', url: TRACE }];
  answer = null;
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => states.shift() });
  assert.deepEqual(await destination(EVIDENCE, { sleep: async (ms) => sleeps.push(ms) }), { state: 'found', url: TRACE });
  assert.deepEqual(sleeps, [1500, 1500], 'a look every second and a half, with nobody pressing again');
  assert.equal(states.length, 0);
});

test('a lookup that Gamma keeps answering "not yet" ends, and says so rather than going on for ever', async () => {
  let clock = 0;
  let looks = 0;
  globalThis.fetch = async () => { looks += 1; return { ok: true, status: 200, json: async () => ({ state: 'pending' }) }; };
  assert.deepEqual(await destination(EVIDENCE, { sleep: async (ms) => { clock += ms; }, now: () => clock }), { state: 'down', url: null });
  assert.ok(looks > 5 && looks < 40, `${looks} looks`);
});

test('what Gamma has none of is said first, in the app, and the list that opens instead takes the person away only after a beat to read it', async () => {
  sent.length = 0;
  page.ids.toasts.replaceChildren();
  const list = 'http://gamma.test/environments/default/aim/observe/logs?q=abc&v=1';
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ state: 'missing', url: list }) });
  assert.deepEqual(await destination(EVIDENCE), { state: 'missing', url: list });
  mock.timers.enable({ apis: ['setTimeout'] });
  try {
    const logs = link({ href: '/api/evidence?kind=logs&api=llm&request=req-12345678&at=1', 'data-gamma': '' });
    page.doc.dispatchEvent(new Ev('click', { target: logs }));
    await flush();
    assert.match(text(page.ids.toasts), /Gamma has no log of this call\. Its logs are open instead\./, 'said where the person is, before the Gamma tab hides the app');
    assert.deepEqual(sent, [], 'nothing has taken the person away yet');
    assert.equal(logs.getAttribute('aria-busy'), 'true', 'a second press, while the sentence is read, starts nothing');
    mock.timers.tick(BEAT - 1);
    await flush();
    assert.deepEqual(sent, [], 'a moment to read it');
    mock.timers.tick(1);
    await flush();
    assert.deepEqual(sent.map((s) => s.message.url), LAB_ORIGINS.map(() => list), 'the list is what is left: it is where the person lands, once they have read why');
    assert.equal(logs.getAttribute('aria-busy'), null);
  } finally {
    mock.timers.reset();
  }
  page.ids.toasts.replaceChildren();
});

test('Gamma that does not answer opens nothing and says so at once, the same as the page of a tab of its own', async () => {
  sent.length = 0;
  page.ids.toasts.replaceChildren();
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ state: 'down' }) });
  const decisions = link({ href: '/api/evidence?kind=decisions&api=mcp&request=req-12345678&at=1', 'data-gamma': '' });
  page.doc.dispatchEvent(new Ev('click', { target: decisions }));
  await flush();
  assert.equal(text(page.ids.toasts), GAMMA_DOWN);
  assert.deepEqual(sent, [], 'the person stays where they are: no tab is switched to show nothing');
  assert.equal(decisions.getAttribute('aria-busy'), null, 'and can press it again');
  page.ids.toasts.replaceChildren();
});

test('the words of a link are those of its kind, and a kind that is not one has none', () => {
  assert.equal(wordsOf(EVIDENCE).looking, 'Looking for the trace in Gamma...');
  for (const odd of ['/api/evidence?kind=constructor&api=a2a&request=r&at=1', '/api/evidence?kind=__proto__&api=a2a', '/api/evidence?api=a2a', 'http://gamma.test/x', undefined]) assert.equal(wordsOf(odd), null, String(odd));
});

test('an answer that is not a page of Gamma is not followed, whatever the app says', async () => {
  for (const body of [{ state: 'found', url: '/api/evidence?kind=trace' }, { state: 'found', url: 'javascript:alert(1)' }, { state: 'found', url: '//evil.example/x' },
    { state: 'found' }, { state: 'missing', url: null }, { state: 'down' }, { state: 'surprise', url: TRACE }, null, 'text']) {
    globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => body });
    assert.deepEqual(await destination(EVIDENCE), { state: 'down', url: null }, JSON.stringify(body));
  }
});

test('what is not an address the page may follow is not posted, and neither is evidence that could not be looked up', async () => {
  sent.length = 0;
  assert.deepEqual(await destination('javascript:alert(1)'), { state: 'down', url: null });
  assert.deepEqual(await destination('//evil.example/x'), { state: 'down', url: null });
  assert.deepEqual(await destination('/api/trace?api=a2a&transaction=abc'), { state: 'down', url: null }, 'a link kept by an older page: nothing to follow');
  assert.deepEqual(await destination(undefined), { state: 'down', url: null });
  globalThis.fetch = async () => ({ ok: false, status: 502, json: async () => ({ error: 'down' }) });
  const lost = link({ href: EVIDENCE, 'data-gamma': '' });
  page.doc.dispatchEvent(new Ev('click', { target: lost }));
  await flush();
  assert.deepEqual(sent, []);
  assert.match(text(page.ids.toasts), /Can't open this in Gamma yet/, 'and the person is told, not left with a button that did nothing');
  assert.equal(lost.getAttribute('aria-busy'), null);
});

test('a lookup that takes a moment says it is looking, in the words of what it looks for, and one that does not says nothing', async () => {
  page.ids.toasts.replaceChildren();
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const lookups = new Map();
  globalThis.fetch = (path) => new Promise((resolve) => { lookups.set(new URLSearchParams(path.split('?')[1]).get('kind'), () => resolve({ ok: true, status: 200, json: async () => ({ state: 'found', url: TRACE }) })); });
  for (const round of [[['trace', 'Looking for the trace in Gamma...'], ['logs', 'Looking for the log in Gamma...']], [['decisions', 'Looking for the decision in Gamma...'], ['spend', 'Looking for the spend in Gamma...']]]) {
    const links = round.map(([kind]) => link({ href: `/api/evidence?kind=${kind}&api=mcp&request=req-12345678&at=1`, 'data-gamma': '' }));
    for (const one of links) page.doc.dispatchEvent(new Ev('click', { target: one }));
    await flush();
    assert.doesNotMatch(text(page.ids.toasts), /Looking/, 'not at once');
    await wait(700);
    for (const [kind, words] of round) assert.ok(text(page.ids.toasts).includes(words), `${kind}: ${text(page.ids.toasts)}`);
    assert.deepEqual(links.map((one) => one.getAttribute('aria-busy')), ['true', 'true']);
    for (const [kind] of round) lookups.get(kind)();
    await flush();
    await wait(300);
    assert.doesNotMatch(text(page.ids.toasts), /Looking/, 'gone when the lookup is over');
    assert.deepEqual(links.map((one) => one.getAttribute('aria-busy')), [null, null]);
  }
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ state: 'found', url: TRACE }) });
  page.doc.dispatchEvent(new Ev('click', { target: link({ href: EVIDENCE, 'data-gamma': '' }) }));
  await flush();
  await wait(700);
  assert.doesNotMatch(text(page.ids.toasts), /Looking/, 'a lookup that was over at once needed no notice');
});

test('a link a model wrote, or any link that is not a way into Gamma, is left alone even inside the Lab UI', async () => {
  sent.length = 0;
  const model = link({ href: 'https://evil.example/login' });
  const event = new Ev('click', { target: model });
  page.doc.dispatchEvent(event);
  await flush();
  assert.equal(event.defaultPrevented, false);
  assert.deepEqual(sent, []);
  globalThis.window.parent = globalThis.window;
});

/* The small tools every part of the page uses, run for real: the link guard, the times, the words. */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { count, duration, initials, safeUrl, usd } from '../../static/js/dom.js';

test('a link the page may follow is one into Gamma or the route of the app that finds the evidence of a call', () => {
  assert.equal(safeUrl('http://localhost:8086/environments/default/aim/observe/logs'), 'http://localhost:8086/environments/default/aim/observe/logs');
  assert.equal(safeUrl('https://gamma.example/x'), 'https://gamma.example/x');
  assert.equal(safeUrl('/api/evidence?kind=logs&api=llm&request=req-12345678&at=1'), '/api/evidence?kind=logs&api=llm&request=req-12345678&at=1');
});

test('anything else is refused: a script, a data page, a page of another site written without a scheme, a thing that is no text', () => {
  for (const url of ['javascript:alert(1)', 'JAVASCRIPT:alert(1)', ' javascript:alert(1)', 'data:text/html,<b>x</b>', '//evil.example/x', '/\\evil.example',
    '/login', '/api/trace?api=llm&transaction=tx-1', '/api/session', '/api/evidence', '/api/evidence/x', 'ftp://x', 'vbscript:x', '', 'https', 'http:/x', 'x https://y']) {
    assert.equal(safeUrl(url), null, JSON.stringify(url));
  }
  for (const url of [undefined, null, 5, {}, ['https://x'], true]) assert.equal(safeUrl(url), null, String(url));
});

test('the words of the page: durations, counts and initials', () => {
  assert.equal(duration(null), '');
  assert.equal(duration(950), '950 ms');
  assert.equal(duration(1500), '1.5 s');
  assert.equal(count(4820), '4,820');
  assert.equal(count(undefined), '');
  assert.equal(initials('Alice Martin'), 'AM');
  assert.equal(initials('Tina'), 'T');
  assert.equal(initials(''), '?');
});

test('money is written with its cents and a separator, and with four decimals only under a cent', () => {
  assert.equal(usd(0.12), '$0.12');
  assert.equal(usd(0.0334), '$0.03');
  assert.equal(usd(0), '$0.00');
  assert.equal(usd(1234.5), '$1,234.50');
  assert.equal(usd(0.0042), '$0.0042');
});

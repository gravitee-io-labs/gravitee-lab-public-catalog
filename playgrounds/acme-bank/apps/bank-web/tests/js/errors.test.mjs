/* What a person is told when a call fails, and what is kept for the person who runs the lab. */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { DOWN_HINT, SLOW_HINT, failure } from '../../static/js/errors.js';
import { waitView } from '../../static/js/wait.js';

const response = (status, error, extra = {}) => ({ ok: false, status, data: { error }, ...extra });

test('an app that cannot be reached is said in plain English, and the container question is folded away', () => {
  assert.deepEqual(failure(response(0, 'The app is not answering')), {
    text: "Can't reach the bank app. Check your connection, then try again.", hint: DOWN_HINT });
  assert.match(DOWN_HINT, /container/);
});

test('a call that gave up is told as a wait that ended, and Ollama stays in the hint', () => {
  const found = failure(response(0, 'No answer after 150 s', { timedOut: true }));
  assert.deepEqual(found, { text: 'No answer came in time. Try again in a minute.', hint: SLOW_HINT });
  assert.match(SLOW_HINT, /Ollama/);
});

test('a call the person stopped is told so, with nothing to look at', () => {
  assert.deepEqual(failure(response(0, 'Stopped', { aborted: true })),
    { text: 'You stopped waiting. Ace may still be working: ask again in a moment.', hint: '' });
});

test('what the app said is shown as it said it, with the hint for a model that did not answer', () => {
  assert.deepEqual(failure(response(504, 'Ace is not answering. Try again in a minute.')), { text: 'Ace is not answering. Try again in a minute.', hint: SLOW_HINT });
  assert.deepEqual(failure(response(401, 'Sign in first')), { text: 'Sign in first', hint: '' });
  assert.deepEqual(failure(response(400, 'message is empty')), { text: 'message is empty', hint: '' });
});

test('a gateway page that is no JSON is not shown as "HTTP 502" alone', () => {
  assert.deepEqual(failure(response(502, 'HTTP 502')), { text: 'Something went wrong (HTTP 502). Try again in a minute.', hint: SLOW_HINT });
  assert.equal(failure({ ok: false, status: 500, data: {} }).text, 'Something went wrong (HTTP 500). Try again in a minute.');
});

test('a slow answer says how long it has been, offers to stop after five seconds and says why it can take long after twelve', () => {
  assert.deepEqual(waitView(0), { text: 'Ace is working - 0 s', canStop: false, slow: false });
  assert.deepEqual(waitView(4), { text: 'Ace is working - 4 s', canStop: false, slow: false });
  assert.deepEqual(waitView(5), { text: 'Ace is working - 5 s', canStop: true, slow: false });
  assert.deepEqual(waitView(14), { text: 'Ace is working - 14 s', canStop: true, slow: true });
});

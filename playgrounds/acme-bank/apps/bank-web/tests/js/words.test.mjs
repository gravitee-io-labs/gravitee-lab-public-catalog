/* The words the page says about the evidence of a call, pinned: the guide quotes the buttons, and every kind of evidence says what it opens, what it is
   looking for and what it does when Gamma has none. */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { EVIDENCE, GAMMA_DOWN, TRY_AGAIN } from '../../static/js/words.js';

test('each kind of evidence says what its button opens, what the page says while it looks, and what it says when Gamma has none', () => {
  assert.deepEqual(Object.keys(EVIDENCE), ['trace', 'logs', 'decisions', 'spend']);
  for (const [kind, words] of Object.entries(EVIDENCE)) {
    assert.match(words.title, /, in Gamma$/, kind);
    assert.doesNotMatch(words.title, /\{/, `${kind}: a sentence, not a template`);
    assert.match(words.looking, /^Looking for the \w+ in Gamma\.\.\.$/, kind);
    assert.match(words.missing, /instead\.$/, kind);
  }
  assert.deepEqual(Object.values(EVIDENCE).map((words) => words.title), ['The trace of this call, in Gamma', 'The log entry of this call, in Gamma',
    'The decision about this call, in Gamma', 'What the run spent, in Gamma']);
});

test('the page says it plainly when Gamma cannot be reached, and offers to try again', () => {
  assert.equal(GAMMA_DOWN, "Can't open this in Gamma yet. Try again in a few seconds.");
  assert.equal(TRY_AGAIN, 'Try again');
});

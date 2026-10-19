/* The page's store: which answer is selected in each view, and the one flag for "something is running". */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { installPage } from './page.mjs';

installPage();
const store = await import('../../static/js/store.js');
const { bus } = await import('../../static/js/dom.js');
const { state } = store;

let n = 0;
const turn = (view = 'assistant', extra = {}) => { n += 1; return { id: `t${n}`, view, n, ...extra }; };
const reset = () => {
  state.turns.clear();
  state.selected = { assistant: null, teams: null, developers: null };
  state.pinned = { assistant: false, teams: false, developers: false };
  state.hold = null;
};

test('the newest answer is selected as it comes, unless the person chose an older one; the answer to a command always is', () => {
  reset();
  const first = turn();
  const second = turn();
  store.addTurn(first);
  store.addTurn(second);
  assert.equal(state.selected.assistant, second.id);
  store.selectTurn(first.id);                                       // the person looks at an older answer
  assert.equal(state.pinned.assistant, true);
  const third = turn();
  store.addTurn(third);
  assert.equal(state.selected.assistant, first.id, 'a new answer does not take the place of the one being read');
  const asked = turn();
  store.addTurn(asked, { select: true });
  assert.equal(state.selected.assistant, asked.id);
  assert.equal(state.pinned.assistant, false);
});

test('choosing the newest answer follows the conversation again, and every view has its own selection', () => {
  reset();
  const a = turn();
  const b = turn();
  const team = turn('teams');
  [a, b, team].forEach((t) => store.addTurn(t));
  store.selectTurn(a.id);
  store.selectTurn(b.id);
  assert.equal(state.pinned.assistant, false);
  assert.deepEqual([store.subjectOf('assistant').id, store.subjectOf('teams').id, store.subjectOf('developers')], [b.id, team.id, null]);
});

test('the selection says it changed, once, to the view it is about', () => {
  reset();
  const heard = [];
  bus.on('selected', (view) => heard.push(view));
  store.addTurn(turn('teams'));
  store.addTurn(turn('developers'));
  assert.deepEqual(heard, ['teams', 'developers']);
});

test('a turn that is taken back leaves the selection to the newest one left; a view whose turns are forgotten selects nothing', () => {
  reset();
  const a = turn();
  const b = turn();
  store.addTurn(a);
  store.addTurn(b);
  store.dropTurn(b.id);
  assert.equal(state.selected.assistant, a.id);
  store.forgetTurns('assistant');
  assert.equal(store.subjectOf('assistant'), null);
  assert.equal(store.turnsOf('assistant').length, 0);
});

test('one flag says something is running, whatever it is, until every one of them has ended', () => {
  assert.equal(store.isBusy(), false);
  const chat = store.begin();
  const teams = store.begin();
  assert.equal(store.isBusy(), true);
  chat();
  assert.equal(store.isBusy(), true);               // a team's answer is still on its way
  chat();                                           // ending twice changes nothing
  assert.equal(store.isBusy(), true);
  teams();
  assert.equal(store.isBusy(), false);
});

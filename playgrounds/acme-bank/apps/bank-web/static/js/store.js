/* What the page knows: who asks, who is signed in, how the gateway is set, the commands the app lists, the answers on the screen and which one is selected. */
import { bus } from './dom.js';

export const DOCKED = window.matchMedia('(min-width: 1280px)');      // Behind the answer sits beside the conversation (a sheet below: there is no room for three columns)
export const PHONE = window.matchMedia('(max-width: 639px)');       // one pane at a time, a bar of views at the bottom, the commands are a tab

export const state = {
  personas: [],
  persona: null,                // who asks now
  signed: [],                   // everybody who is signed in here (their tokens are the server's): choosing one of them is instant, choosing another is a sign-in
  gateway: true,                // through the Gravitee gateway
  groups: [],                   // the commands, grouped under the title of a lesson of the guide
  commandsError: '',            // why there are none, when the app did not give them
  budgetCalls: 4,               // long answers the budget command asks for, at most (the server says)
  config: { gamma_url: '', pages: {} },
  view: 'assistant',
  railOpen: true,               // the commands are shown (a slim strip when they are not); the router decides
  running: null,                // the command being run
  busy: false,                  // Ace is answering in the conversation
  conversation: 0,              // changes with the person: an answer for another conversation is dropped
  turns: new Map(),             // what "Behind the answer" can show, by turn id: an answer of Ace, a payment, an answer of a team or of the LLM proxy
  selected: { assistant: null, teams: null, developers: null },      // the turn each view's "Behind the answer" shows: one at a time
  pinned: { assistant: false, teams: false, developers: false },     // the person chose an older answer: a new one does not take the place
  hold: null,                   // the view whose answer is being read in the sheet: a new answer does not take its place under the reader's eyes
  mode: 'ask',                  // the composer: a question for Ace, or a payment by the person
  working: false,               // a call takes long: Behind the answer shows a skeleton
  team: 'team-hackathon',
};

/* ---- what is selected: the answer Behind the answer shows ---------------------------------------------------------------- */

export const turnsOf = (view) => [...state.turns.values()].filter((turn) => turn.view === view);

/* A new turn is selected, unless the person chose an older one to look at, or is reading one in the sheet (then it stays); the answer to a
   command always is (`select`). */
export function addTurn(subject, { select = false } = {}) {
  state.turns.set(subject.id, subject);
  if (select || (!state.pinned[subject.view] && state.hold !== subject.view)) {
    state.selected[subject.view] = subject.id;
    state.pinned[subject.view] = false;
  }
  bus.emit('selected', subject.view);
}

/* The person chooses a turn: the newest is the one that follows the conversation, an older one stays. */
export function selectTurn(id) {
  const subject = state.turns.get(id);
  if (!subject) return false;
  const newest = turnsOf(subject.view).pop();
  state.selected[subject.view] = id;
  state.pinned[subject.view] = !(newest && newest.id === id);
  bus.emit('selected', subject.view);
  return true;
}

export const subjectOf = (view) => state.turns.get(state.selected[view]) || null;

/* A view follows its conversation again: the newest turn is the one selected, unless the person chose an older one. */
export function followNewest(view) {
  if (state.pinned[view]) return;
  const newest = turnsOf(view).pop();
  state.selected[view] = newest ? newest.id : null;
  bus.emit('selected', view);
}

/* A view's turns are gone (another person asks): nothing is selected. */
export function forgetTurns(view) {
  for (const [id, turn] of state.turns) if (turn.view === view) state.turns.delete(id);
  state.selected[view] = null;
  state.pinned[view] = false;
  bus.emit('selected', view);
}

/* A turn is taken back (the question is asked again): it is not selected. */
export function dropTurn(id) {
  const turn = state.turns.get(id);
  if (!turn) return;
  state.turns.delete(id);
  if (state.selected[turn.view] === id) {
    state.pinned[turn.view] = false;
    followNewest(turn.view);
  }
  bus.emit('selected', turn.view);
}

/* One flag for everything that is running: a command, a conversation, a payment, a team's answer, the Presenter's check. A command does
   not start while any of them is going on. `begin()` returns what ends it. */
const tasks = new Set();
export const isBusy = () => tasks.size > 0;
export function begin() {
  const task = Symbol('work');
  tasks.add(task);
  bus.emit('busy');
  return () => { if (tasks.delete(task)) bus.emit('busy'); };
}

/* The conversation with Ace: the question, the wait, the answer. What the gateway did on the way is Behind the answer (inspector.js): the conversation shows
   what was said, and which answer is selected. A question typed here and a command of the rail are asked the same way and answered the same way. */
import { $, h, api, bus } from './dom.js';
import { failure } from './errors.js';
import { icon } from './icons.js';
import { state, addTurn, begin, dropTurn, forgetTurns } from './store.js';
import { askAs, follow } from './session.js';
import { behindButton, clock } from './inspector.js';
import { box, clearEmpty, clicked, failedSubject, firstName, markSelected, pickButton, problem, scrollDown } from './turns.js';
import { clamped, empty, say } from './ui.js';
import { waitView } from './wait.js';

const ASK_TIMEOUT = 150 * 1000;           // Ace's own limit is 120 s: past this nothing is coming
let turnCounter = 0;                      // never starts again: an answer of a conversation that was left keeps its own number
let lastAsked = null;
let endWork = null;                       // ends the shared "something is running" of the conversation (see store.js)

/* ---- the empty conversation ------------------------------------------------------------------------------------- */

/* A conversation with no message in it says so, in one line, whoever is asking and wherever the commands are. */
function emptyNode() {
  const node = empty('ace', 'No message yet. Ask Ace a question, or run a command.');
  node.setAttribute('data-empty', '');
  return node;
}

function resetConversation() {
  forgetTurns('assistant');
  state.working = false;
  box().replaceChildren(emptyNode());
  setBusy(false);
  bus.emit('selected', 'assistant');
}

/* Send is for a question: it waits for words and for the answer before. */
function syncSend() {
  $('#send').disabled = state.busy || !$('#message').value.trim();
}

function setBusy(busy) {
  state.busy = busy;
  if (busy && !endWork) endWork = begin();
  if (!busy && endWork) { endWork(); endWork = null; }
  syncSend();
  $('#composer').setAttribute('aria-busy', String(busy));
  bus.emit('busy');
}

/* ---- the pieces of a conversation ------------------------------------------------------------------------------- */

const userBubble = (text) => h('div', { class: 'msg user' }, h('div', { class: 'bubble', text }));

/* The wait: what the page knows (how long it has been), a way out after a few seconds, and after a few more a word on why it can take long. `controller` stops the call. */
function pending(controller) {
  const working = h('span', { class: 'working', text: 'Ace is working - 0 s' });
  const stopButton = h('button', { type: 'button', class: 'link-button stop', hidden: true, onclick: () => controller.abort() }, 'Stop');
  const slow = h('div', { class: 'slow-note', hidden: true, text: 'A model on this machine can take a minute.' });
  const node = h('div', { class: 'msg ace', 'aria-busy': 'true' }, h('span', { class: 'tile sm' }, icon('ace')),
    h('div', { class: 'bubble typing' }, h('div', { class: 'dots', 'aria-hidden': 'true' }, h('i'), h('i'), h('i')),
      h('div', { class: 'working-row' }, working, stopButton), slow));
  const started = Date.now();
  const tick = () => {
    const view = waitView(Math.floor((Date.now() - started) / 1000));
    working.textContent = view.text;
    stopButton.hidden = !view.canStop;
    slow.hidden = !view.slow;
    if (view.canStop !== state.working) { state.working = view.canStop; bus.emit('selected', 'assistant'); }       // a call that takes long: Behind the answer waits too
  };
  const timer = setInterval(tick, 1000);
  say('Ace is working');
  return { node, stop() {
    clearInterval(timer);
    node.remove();
    say('');                     // what was said of the wait is not left for a screen reader to find: the answer or the alert says what came
    if (state.working) { state.working = false; bus.emit('selected', 'assistant'); }
  } };
}

/* The answer, when it came, whether it went direct, and, where Behind the answer is not beside it, the control that opens it (under the selected one). */
function aceMessage(subject, result) {
  return h('article', { class: 'msg ace', 'data-turn': subject.id, onclick: (event) => clicked(event, subject.id) },
    h('span', { class: 'tile sm' }, icon('ace')),
    h('div', { class: 'reply' }, h('div', { class: 'bubble' }, clamped(result.answer, 'long-answer')),
      h('div', { class: 'meta' }, h('span', { class: 'time', text: clock(subject.at) }), subject.gateway ? null : h('span', { class: 'route', text: 'Direct' }), behindButton(subject.id)),
      pickButton(subject)));
}

/* What a screen reader says of an answer: Ace's own words first (the first 200 characters, as plain text). */
export function spoken(answer) {
  const reply = String(answer || '').replace(/[*`#|]/g, '').replace(/\s+/g, ' ').trim();
  return reply ? `Ace says: ${reply.length > 200 ? `${reply.slice(0, 200)}...` : reply}` : 'Ace answered.';
}

function retryAction(retry) {
  return h('button', { type: 'button', class: 'btn btn-sm', onclick: (event) => {
    const failed = event.currentTarget.closest('.msg');
    const asked = failed.previousElementSibling;            // the question that got no answer is asked again, not shown twice
    if (asked && asked.classList.contains('user')) asked.remove();
    dropTurn(failed.dataset.turn);
    failed.remove();
    retry();
  } }, icon('reset', 'sm'), 'Try again');
}

/* An answer, or what to do when there is none. Returns the result when there is one. `asked`: { text, started }. `command`: the answer is the one a command of
   the rail asked for, and it is selected. */
function finish(response, wait, epoch, { command = null, retry = null, focus = true, asked }) {
  wait.stop();
  if (epoch !== state.conversation) return null;
  turnCounter += 1;
  const id = `t${turnCounter}`;
  if (!response.ok) {
    follow(response.data.who);
    const actions = [];
    if (!state.persona || response.status === 401) {          // a 401 is a person who is not signed in (nobody, the one the server forgot, or the one a command is for): the way on is to choose who asks
      /* the click that opens the menu must not go on to the document, which closes a menu for a click outside it: it would close it at once */
      actions.push(h('button', { type: 'button', class: 'btn btn-sm', onclick: (event) => { event.stopPropagation(); $('#person-button').click(); } }, icon('user', 'sm'), 'Choose who is asking'));
    } else if (retry) actions.push(retryAction(retry));
    const { text, hint } = failure(response);
    const subject = failedSubject(id, turnCounter, response, { ...asked, title: `${firstName()} asked Ace`, message: text });
    addTurn(subject, { select: Boolean(command) });
    box().append(problem(text, actions, hint, subject));
    markSelected();
    scrollDown();
    setBusy(false);
    const action = box().querySelector('.msg.problem:last-child .btn');
    if (action) action.focus({ preventScroll: true });
    return null;
  }
  follow(response.data.who);
  const result = response.data;
  const subject = { id, view: 'assistant', kind: 'chat', n: turnCounter, at: Date.now(), ms: result.ms, gateway: result.protected, rows: result.rows,
    line: `${clock(Date.now())} · ${asked.text}` };
  addTurn(subject, { select: Boolean(command) });
  box().append(aceMessage(subject, result));
  markSelected();
  scrollDown();
  setBusy(false);
  if (focus && state.persona) $('#message').focus({ preventScroll: true });
  say(spoken(result.answer));
  return result;
}

/* ---- asking ----------------------------------------------------------------------------------------------------- */

/* Sends a question, whoever it comes from: `url` and `body` are the route that answers it. */
async function send({ text, url, body, command = null, focus = true, retry }) {
  const epoch = state.conversation;
  setBusy(true);
  clearEmpty();
  box().append(userBubble(text));
  const controller = new AbortController();
  const started = Date.now();
  const wait = pending(controller);
  box().append(wait.node);
  scrollDown();
  const response = await api(url, { method: 'POST', body, timeout: ASK_TIMEOUT, controller });
  return finish(response, wait, epoch, { command, focus, retry, asked: { text, started } });
}

/* A question is asked as somebody: where nobody is, the menu of who is asking opens (the question stays in the box), and the person sends it when they are back. */
export async function ask(text) {
  text = text.trim();
  if (state.busy || !text) return null;
  if (!state.persona) {
    $('#person-button').click();
    return null;
  }
  lastAsked = text;
  $('#message').value = '';
  autosize();
  return send({ text, url: '/api/chat', body: { message: text, gateway: state.gateway ? 'on' : 'off' }, retry: () => ask(lastAsked) });
}

/* A command of the rail that asks Ace something: as the person it is for, in the same conversation, with their token if they are signed in and without one if they are
   not (the gateway refuses the question, and that refusal is the answer). A command never inherits the control of the head: it carries its own route, and only the one
   that says so goes without the gateway (the server knows which). */
export async function playChat(command) {
  if (state.busy) return null;
  await askAs(command.persona);
  return send({ text: command.message, url: `/api/commands/${command.id}/run`, body: {}, command, focus: false, retry: () => playChat(command) });
}

function autosize() {
  const field = $('#message');
  field.style.height = 'auto';
  field.style.height = `${Math.min(field.scrollHeight, 160)}px`;
  field.style.overflowY = field.scrollHeight > 160 ? 'auto' : 'hidden';
}

export function initChat() {
  $('#composer').addEventListener('submit', (event) => {
    event.preventDefault();
    ask($('#message').value);
  });
  $('#message').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      ask($('#message').value);
    }
  });
  $('#message').addEventListener('input', () => { autosize(); syncSend(); });
  bus.on('persona', ({ changed } = {}) => setBusy(state.busy && !changed));
  bus.on('conversation-reset', resetConversation);
  bus.on('selected', (view) => { if (view === 'assistant') markSelected(); });
  box().replaceChildren(emptyNode());
  setBusy(false);
}

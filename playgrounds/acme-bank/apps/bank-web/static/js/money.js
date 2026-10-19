/* Send money: the person calls transfer_funds with their own token. No agent in between, so the same amount can be allowed here and denied when
   Ace asks for it. The payment is a turn of the conversation, with its receipt, and it can be selected like an answer: its call is Behind it. */
import { $, h, api, bus } from './dom.js';
import { icon } from './icons.js';
import { state, begin, addTurn } from './store.js';
import { askAs, follow } from './session.js';
import { failure } from './errors.js';
import { behindButton, clock } from './inspector.js';
import { box, clearEmpty, clicked, failedSubject, firstName, markSelected, pickButton, problem, scrollDown } from './turns.js';
import { say, toast } from './ui.js';

let paying = false;
let counter = 0;
const TIMEOUT = 60 * 1000;

function syncForm() {
  const who = state.persona;
  $('#money-send').disabled = paying;
  if (who && !paying) {
    $('#money-from').value = who.send.from;
    $('#money-to').value = who.send.to;
    $('#money-amount').value = who.send.amount;
    $('#money-ref').value = '';
  }
  if (!who) for (const id of ['from', 'to', 'amount', 'ref']) $(`#money-${id}`).value = '';
}

const euros = (amount) => `EUR ${Number(amount).toLocaleString('en-US', { maximumFractionDigits: 2 })}`;

/* The payment, as the conversation tells it: what was sent, whether it moved, when, and that no agent was involved. Where Behind the answer is
   not beside it, the control that opens it. */
function receipt(subject, request, result) {
  const moved = result.tone === 'ok';
  return h('article', { class: 'msg pay', 'data-turn': subject.id, onclick: (event) => clicked(event, subject.id) },
    h('span', { class: 'tile sm' }, icon('send')),
    h('div', { class: 'reply' },
      h('div', { class: 'bubble receipt' },
        h('div', { class: 'receipt-what' }, h('strong', { text: euros(request.amount) }), ` from ${request.from} to ${request.to}${request.reference ? `, reference ${request.reference}` : ''}`),
        h('div', { class: `receipt-state ${moved ? 'moved' : 'refused'}`, text: moved ? 'Moved' : 'Not moved' })),
      h('div', { class: 'meta' }, h('span', { class: 'time', text: clock(subject.at) }), h('span', { class: 'route', text: result.protected ? 'without Ace' : 'without Ace · Direct' }), behindButton(subject.id)),
      pickButton(subject)));
}

function working() {
  const node = h('div', { class: 'msg pay', 'aria-busy': 'true' }, h('span', { class: 'tile sm' }, icon('send')),
    h('div', { class: 'bubble typing' }, h('div', { class: 'progress-line', role: 'status' }, h('span', { class: 'spinner' }), 'Calling transfer_funds')));
  box().append(node);
  scrollDown();
  return node;
}

/* One payment, whoever started it (the form, or a command of the rail): `send` makes the call. `command`: the receipt is selected. */
async function run({ send, request, command = null }) {
  const epoch = state.conversation;
  paying = true;
  const done = begin();
  $('#money-send').disabled = true;
  clearEmpty();
  const wait = working();
  const started = Date.now();
  const response = await send();
  paying = false;
  done();
  wait.remove();
  if (epoch !== state.conversation) return null;
  follow(response.data.who);      // the cookie is shared by the tabs of a browser: the payment was made by whoever it says
  $('#money-send').disabled = false;
  counter += 1;
  const id = `p${counter}`;
  if (!response.ok) {
    const { text, hint } = failure(response);
    const subject = failedSubject(id, counter, response, { text: `Payment of ${euros(request.amount)}`, started, title: `${firstName()} called transfer_funds`, message: text });
    addTurn(subject, { select: Boolean(command) });
    box().append(problem(text, [], hint, subject));
    markSelected();
    scrollDown();
    return null;
  }
  const result = response.data;
  const subject = { id, view: 'assistant', kind: 'payment', n: counter, at: Date.now(), ms: result.ms, gateway: result.protected, rows: [result],
    line: `${clock(Date.now())} · Payment of ${euros(request.amount)}` };
  addTurn(subject, { select: Boolean(command) });
  box().append(receipt(subject, request, result));
  markSelected();
  scrollDown();
  say(`${result.tone === 'ok' ? 'Moved' : 'Not moved'}: ${euros(request.amount)}`);
  return result;
}

async function submit(event) {
  event.preventDefault();
  if (paying) return;
  if (!state.persona) {          // a payment is made by somebody: the menu of who is asking opens, and the person pays when they are back
    $('#person-button').click();
    return;
  }
  const amount = $('#money-amount').valueAsNumber;
  if (Number.isNaN(amount)) {
    toast('Enter an amount in EUR.', 'info');
    $('#money-amount').focus();
    return;
  }
  const request = { from: $('#money-from').value, to: $('#money-to').value, amount, reference: $('#money-ref').value };
  await run({ request, send: () => api('/api/send-money', { method: 'POST', timeout: TIMEOUT, body: {
    from_account: request.from, to_account: request.to, amount, reference: request.reference, gateway: state.gateway ? 'on' : 'off' } }) });
}

/* A command of the rail that moves money as the person, with no agent: its payment is a turn of the conversation. It is through the gateway, whatever the
   control of the head says: the server knows. With the person's token if they are signed in, and without one if they are not: the gateway refuses the payment. */
export async function playMoney(command) {
  if (paying) return null;
  await askAs(command.persona);
  const { from_account: from, to_account: to, amount } = command.transfer;
  return run({ command, request: { from, to, amount, reference: '' },
    send: () => api(`/api/commands/${command.id}/run`, { method: 'POST', timeout: TIMEOUT, body: {} }) });
}

export function initMoney() {
  $('#money-form').addEventListener('submit', submit);
  bus.on('persona', syncForm);
  bus.on('conversation-reset', syncForm);
  syncForm();
}

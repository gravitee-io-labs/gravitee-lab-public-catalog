/* The commands: ready-made questions and actions, a list beside the conversation, grouped under the title of the lesson of the guide that uses them.
   One click asks as the person a command is for (with their token if they are signed in, without one if they are not: the gateway then says no), and shows the
   answer where any answer is shown (the conversation, Teams for the budget), selected for Behind the answer. A command signs nobody in: the person control does. The list is always whole: no group opens or closes, and it knows nothing of what the platform did with a command, so there is
   nothing to keep in step with it. The one thing it holds besides the commands is "Start the bank over", at its foot. On a phone it is a tab of its own. */
import { $, $$, h, api, bus, reducedMotion } from './dom.js';
import { failure } from './errors.js';
import { icon } from './icons.js';
import { state, begin, isBusy, PHONE } from './store.js';
import { startOver } from './bank.js';
import { playChat } from './chat.js';
import { playMoney } from './money.js';
import { runBudget } from './teams.js';
import { empty, skeleton, toast } from './ui.js';

const place = () => $('#rail');
const collapsed = () => !PHONE.matches && !state.railOpen;          // a phone has no strip: the commands are a tab of their own

/* Who a command is for, as its first name, when it is for somebody (the budget command is for a team, and says so in its label). */
function whoOf(command) {
  const who = command.persona ? state.personas.find((p) => p.id === command.persona) : null;
  return who ? who.name.split(' ')[0] : '';
}

/* ---- one command, and the group it is in ----------------------------------------------------------------------------------------- */

function commandNode(command) {
  const who = whoOf(command);
  return h('li', {}, h('button', { type: 'button', class: 'command', 'data-key': command.id, 'aria-label': who ? `${command.label}, as ${who}` : command.label,
    'aria-busy': 'false', onclick: () => runCommand(command) },
  h('span', { class: 'play' }, icon('play')),
  h('span', { class: 'command-label', text: command.label }),
  who ? h('span', { class: 'command-who', text: who }) : null));
}

function groupNode(group) {
  const id = `group-${group.id}`;
  return h('section', { class: 'group', 'aria-labelledby': id },
    h('h3', { class: 'group-title', id }, h('span', { class: 'group-no', text: String(group.id) }), ' ', h('span', { text: group.title })),
    h('ul', { class: 'group-commands' }, group.commands.map(commandNode)));
}

/* ---- the rail ------------------------------------------------------------------------------------------------------------------------ */

const edge = (open) => h('button', { type: 'button', class: 'icon-btn rail-edge', 'data-key': 'edge', 'aria-label': open ? 'Collapse the commands' : 'Show the commands',
  title: open ? 'Collapse the commands' : 'Show the commands', onclick: () => bus.emit('rail', !open) }, icon(open ? 'chevron-left' : 'chevron-right'));

/* The commands as a slim strip, with the edge control that opens them again and the name of what it holds. */
const buildStrip = () => h('div', { class: 'commands rail-strip' }, edge(false), h('span', { class: 'strip-title', 'aria-hidden': 'true', text: 'Commands' }));

function build(collapsible) {
  const head = h('div', { class: 'commands-head' }, h('h2', { text: 'Commands' }), collapsible ? edge(true) : null);
  if (state.commandsError) {
    return h('div', { class: 'commands' }, head, empty('alert', 'The commands are not available', state.commandsError,
      h('button', { type: 'button', class: 'btn btn-sm', 'data-key': 'reload', onclick: () => loadCommands() }, icon('reset', 'sm'), 'Reload')));
  }
  if (!state.groups.length) return h('div', { class: 'commands' }, head, skeleton(6));
  return h('div', { class: 'commands' }, head,
    h('div', { class: 'groups' }, state.groups.map(groupNode),
      h('div', { class: 'rail-foot' }, h('button', { type: 'button', class: 'btn btn-quiet', 'data-key': 'start-over', onclick: () => startBankOver() },
        icon('reset'), h('span', { text: 'Start the bank over' })))));
}

/* What the rail draws depends on this and on nothing else: a change that touches none of it does not draw it again, so a hover, the scroll and the screen
   reader's place stay. What a run changes (which command runs, that the others wait) is written in place by `paint`. */
const signature = () => JSON.stringify([PHONE.matches, collapsed(), state.commandsError, state.groups.length, state.personas.length]);

let drawn = '';

export function renderCommands() {
  const now = signature();
  if (now === drawn && place().firstChild) return;
  drawn = now;
  const focused = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.key : null;
  const here = place();
  here.replaceChildren(collapsed() ? buildStrip() : build(!PHONE.matches));
  if (focused) {
    const again = here.querySelector(`[data-key="${CSS.escape(focused)}"]`);
    if (again) again.focus({ preventScroll: true });
  }
  paint();
}

/* The command that runs shows a turning mark in place of its play mark; the others, and the bank over, wait (`aria-disabled`, not `disabled`: the focus
   stays where the person put it). Written in place: the rail is not drawn again, so it keeps its scroll under the person's pointer. */
function paint() {
  const busy = isBusy();
  for (const button of $$('.command', place())) {
    const running = state.running === button.dataset.key;
    button.classList.toggle('running', running);
    button.setAttribute('aria-busy', String(running));
    const play = button.querySelector('.play');
    if (play && Boolean(play.querySelector('.spinner')) !== running) play.replaceChildren(running ? h('span', { class: 'spinner' }) : icon('play'));
  }
  for (const button of $$('.command, .rail-foot .btn', place())) {
    if (busy) button.setAttribute('aria-disabled', 'true');
    else button.removeAttribute('aria-disabled');
  }
}

/* The command takes the focus back when its run is over (where the rail is shown), and comes into view: the person goes on from where they were. A run
   the guide asked for (inside the Lab UI) leaves the focus where it is, in the guide: this page does not have it. */
function focusBack(commandId) {
  const button = place().querySelector(`[data-key="${CSS.escape(commandId)}"]`);
  if (!button || button.offsetParent === null || !document.hasFocus()) return;
  button.focus({ preventScroll: true });
  button.scrollIntoView({ block: 'nearest', behavior: reducedMotion() ? 'auto' : 'smooth' });
}

/* ---- running a command ---------------------------------------------------------------------------------------------------------------- */

/* What a command uses: the page's state and the parts of the page that play it. A test hands in its own. */
const PORTS = { state, isBusy, begin, bus, toast, playChat, playMoney, runBudget, focusBack };

/* Sends the question or makes the payment or spends the budget, as the person the command is for, and shows the answer where it belongs: the Assistant, or Teams for
   the budget (on a phone that is another tab than the commands, so the person goes there). No question asked first, no wait counted here: the conversation says that. */
export async function runCommand(command, ports = PORTS) {
  if (ports.state.running || ports.isBusy()) {
    ports.toast('Something is still running. Run it when it is done.', 'info');
    return;
  }
  ports.state.running = command.id;
  const done = ports.begin();
  ports.bus.emit('running');
  try {
    if (command.kind === 'budget') {
      ports.bus.emit('go', 'teams');
      await ports.runBudget(command);
    } else {
      ports.bus.emit('go', 'assistant');
      if (command.kind === 'money') await ports.playMoney(command);
      else await ports.playChat(command);
    }
  } finally {
    ports.state.running = null;
    done();
    ports.bus.emit('running');
    ports.focusBack(command.id);
  }
}

/* "Start the bank over", at the foot of the commands: the money and the cards go back. */
async function startBankOver() {
  if (isBusy()) return;
  await startOver();
}

/* The commands, from the app. Where it cannot be reached the rail says so and has a button; it asks again by itself when the tab gets the focus back or the
   connection returns. */
export async function loadCommands() {
  const response = await api('/api/commands');
  if (!response.ok) {
    state.commandsError = failure(response).text;
  } else {
    state.commandsError = '';
    state.groups = response.data.groups;
    state.budgetCalls = response.data.budget_calls;
  }
  bus.emit('commands');
  return response.ok;
}

export function initCommands() {
  for (const event of ['commands', 'rail-state']) bus.on(event, renderCommands);
  for (const event of ['running', 'busy']) bus.on(event, paint);
  PHONE.addEventListener('change', renderCommands);
  const again = () => { if (state.commandsError) loadCommands(); };
  window.addEventListener('online', again);
  window.addEventListener('focus', again);
  renderCommands();
}

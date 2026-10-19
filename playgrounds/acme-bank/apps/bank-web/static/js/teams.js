/* Teams: the AI workspace, called with the key of a team (the key stays on the server). Each team has a budget, and the router moves it to the
   cheaper model while it is half spent. Same frame as the Assistant: the team that calls is in the head, the answers come one after the other,
   the budget is the monitor, and the answer that is selected has its call Behind it. */
import { $, h, api, bus, usd } from './dom.js';
import { icon } from './icons.js';
import { failure } from './errors.js';
import { menuOf } from './menus.js';
import { state, addTurn } from './store.js';
import { behindButton } from './inspector.js';
import { clicked, markSelected, pickButton, toEnd, waitingNode } from './turns.js';
import { chip, clamped, empty, hintNode, say, whileBusy } from './ui.js';

const TIMEOUT = 120 * 1000;
let loaded = false;
let teams = [];
let answers = 0;
const data = {};                      // per team: what its last answer said of its budget

const feed = () => $('#team-feed');
const nameOf = (id) => (teams.find((t) => t.id === id) || { name: id }).name;

/* When a budget resets, as the gateway reports it: the window opens at the member's first call. */
function resetsIn(epoch) {
  if (!epoch) return '';
  const minutes = Math.round((epoch - Date.now()) / 60000);
  if (minutes < 1) return 'under a minute';
  return minutes >= 120 ? `${Math.round(minutes / 60)} h` : `${minutes} min`;
}

function renderPicker() {
  $('#team-name').textContent = nameOf(state.team);
  $('#team-button').setAttribute('aria-label', `${nameOf(state.team)}. Change the team`);
}

function choose(id) {
  state.team = id;
  renderPicker();
  renderBudget();
}

/* The budget of the team that calls: what is left, said once; the meter with the 50% where the router moves the team; where the team is now;
   when it resets. What each answer was let in at is the answer's own chip. */
function renderBudget() {
  const box = $('#team-budget');
  const info = data[state.team];
  if (!info || !info.budget) {
    box.replaceChildren(h('div', { class: 'budget-top' }, h('span', { class: 'budget-figure' }, h('span', { class: 'none', text: '—' }), ' ', h('small', { text: 'no call yet' }))),
      h('div', { class: 'meter half', 'aria-hidden': 'true' }, h('i')));
    return;
  }
  const { limit, left, percent_left: percent } = info.budget;
  const meter = h('div', { class: `meter half ${percent === 0 ? 'empty' : percent <= 25 ? 'low' : ''}`.trim(), role: 'meter', 'aria-label': 'Budget left',
    'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(percent), 'aria-valuetext': `${usd(left)} left of ${usd(limit)}` }, h('i'));
  meter.firstChild.style.setProperty('--w', percent);
  box.replaceChildren(
    h('div', { class: 'budget-top' }, h('span', { class: 'budget-figure' }, usd(left), ' ', h('small', { text: `left of ${usd(limit)}` }))),
    meter,
    h('div', { class: 'budget-ends' }, h('span', { class: `end smart ${info.model === 'smart' ? 'here' : ''}`.trim(), text: 'smart' }),
      h('span', { class: 'half-label', text: 'Router switches at 50% spent' }), h('span', { class: `end lite ${info.model === 'lite' ? 'here' : ''}`.trim(), text: 'lite' })),
    info.reset ? h('div', { class: 'budget-foot' }, h('span', { text: 'Resets in ' }), h('b', { text: resetsIn(info.reset) })) : null);
}

/* How much of the budget the gateway counted as spent when it let the answer in: the figure the router decides on. */
function spentOf(budget) {
  return budget && budget.limit > 0 ? Math.round(100 * (1 - budget.left / budget.limit)) : null;
}

/* One answer of a team: its number, how it went, the model that answered (and the one before when the router moved the team), the share of the
   budget spent when it was let in, and the answer. Its call is Behind it: tokens, time, evidence. */
function answerRow(subject, result, previous) {
  const text = result.status === 200 ? result.answer : result.message;
  const spent = spentOf(result.budget);
  const model = result.model ? (previous && previous !== result.model ? `${previous} → ${result.model}` : result.model) : null;
  return h('article', { class: 'answer', 'data-turn': subject.id, onclick: (event) => clicked(event, subject.id) },
    h('div', { class: 'answer-top' }, h('strong', { class: 'num', text: `#${subject.n}` }),
      model ? chip(result.model === 'lite' ? 'lite' : 'smart', model) : null,
      spent === null ? null : chip(spent >= 50 ? 'limit' : 'note', `${spent}% spent`),
      behindButton(subject.id)),
    clamped(text, result.status === 200 ? '' : 'muted'),
    pickButton(subject));
}

function record(result) {
  data[result.team] = { budget: result.budget || (data[result.team] && data[result.team].budget) || null,
    reset: (result.limits && result.limits.reset) || (data[result.team] && data[result.team].reset) || null,
    model: result.model || (data[result.team] && data[result.team].model) || null };
  renderBudget();
}

function addToFeed(node) {
  const box = feed();
  const first = box.firstElementChild;
  if (first && first.classList.contains('empty')) first.remove();
  box.append(node);
  toEnd(box);
}

function problem(response) {
  const { text, hint } = failure(response);
  addToFeed(h('div', { class: 'msg problem' }, h('span', { class: 'tile sm', 'aria-hidden': 'true' }, icon('alert')),
    h('div', { class: 'reply' }, h('div', { class: 'bubble', role: 'alert' }, text), hintNode(hint))));
}

/* An answer of the workspace joins the conversation of the team: a turn that Behind the answer can show. `select`: it is the answer of a command, and it is selected. */
function answered(result, { select = false } = {}) {
  answers += 1;
  const subject = { id: `m${answers}`, view: 'teams', kind: 'team', n: answers, at: Date.now(), ms: result.ms, gateway: true,
    line: `#${answers} · ${nameOf(result.team)}`, rows: result.rows };
  const previous = (data[result.team] || {}).model || null;
  record(result);
  addTurn(subject, { select });
  addToFeed(answerRow(subject, result, previous));
  markSelected('teams', feed());
  say(`Answer ${answers} of ${nameOf(result.team)}: ${result.status === 200 ? String(result.answer || '').replace(/\s+/g, ' ').slice(0, 200) : result.message}`);
  return subject;
}

/* The call on its way: a few dots at the end of the feed, until the answer comes. */
function waiting() {
  const node = waitingNode('users');
  addToFeed(node);
  return node;
}

/* One answer of the team that calls. `since`: when the run it belongs to began, so that its Spend is the whole run's. */
async function call(kind, { since = null, select = false } = {}) {
  const wait = waiting();
  const response = await api('/api/teams/chat', { method: 'POST', body: { team: state.team, kind, ...(since === null ? {} : { since }) }, timeout: TIMEOUT });
  wait.remove();
  if (!response.ok) { problem(response); return null; }
  answered(response.data, { select });
  return response.data;
}

/* A run of answers one after the other, which ends at the first that is not an answer: a 429 says it all. */
async function run(kind, n, { select = false } = {}) {
  const since = Date.now();
  for (let i = 0; i < n; i += 1) {
    const result = await call(kind, { since, select });
    if (!result || result.status !== 200) break;
  }
}

/* The command of the rail: the Hackathon team asks for long answers one after the other (at most `budgetCalls`, the server says how many), until the hour's
   budget is spent and the gateway answers 429. Each answer comes as it is made, with the budget draining; the last one is selected. */
export async function runBudget(command) {
  await loadTeams();
  state.team = command.team;
  renderPicker();
  renderBudget();
  return whileBusy(buttons(), () => run('long', state.budgetCalls, { select: true }));
}

async function loadTeams() {
  if (loaded) return;
  const response = await api('/api/teams');
  if (!response.ok) {
    feed().replaceChildren(empty('alert', 'The teams are not available', failure(response).text));
    return;
  }
  loaded = true;
  teams = response.data.teams;
  renderPicker();
  renderBudget();
}

const buttons = () => ['#team-short', '#team-long', '#team-triple'].map((s) => $(s));

export function initTeams() {
  $('#team-short').addEventListener('click', () => whileBusy(buttons(), () => call('short')));
  $('#team-long').addEventListener('click', () => whileBusy(buttons(), () => call('long')));
  $('#team-triple').addEventListener('click', () => whileBusy(buttons(), () => run('long', 3)));
  menuOf({ button: $('#team-button'), menu: $('#team-menu'), home: $('#team-picker'), items: (close) => teams.map((team) => h('button', {
    type: 'button', role: 'menuitemradio', class: 'menu-item', 'aria-checked': String(team.id === state.team),
    onclick: () => { close(true); choose(team.id); } },
  h('span', { class: 'who' }, h('span', { text: team.name })), team.id === state.team && h('span', { class: 'tick' }, icon('check')))) });
  feed().replaceChildren(empty('wallet', 'No answer yet. Ask for a short or a long answer, or run a command.'));
  renderPicker();
  renderBudget();
  bus.on('view', (view) => { if (view === 'teams') loadTeams(); });
  bus.on('selected', (view) => { if (view === 'teams') markSelected('teams', feed()); });
}

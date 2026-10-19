/* Presenter: is everything ready, warm it up, start the bank over, quiet the traffic. */
import { $, h, api, bus, duration } from './dom.js';
import { icon } from './icons.js';
import { failure } from './errors.js';
import { say, skeleton, toast, whileBusy } from './ui.js';
import { startOver } from './bank.js';

const GROUPS = [['platform', 'Platform'], ['data', 'Traffic and data']];
const MARK = { ok: 'check', warn: 'alert', fail: 'x', wait: 'dot' };
const TRAFFIC_STATES = { waiting: 'Waiting for the platform', 'warming-up': 'Warming up' };

/* A row of the check: its mark, what was checked, and where the answer is (the milliseconds a check took are in its tooltip: they say nothing to a
   person presenting). */
function row(item) {
  return h('li', { class: `check ${item.status}` },
    h('span', { class: 'mark' }, icon(MARK[item.status] || 'dot')),
    h('span', { class: 'what', title: duration(item.ms), text: item.label || item.id }),
    item.detail ? h('span', { class: 'detail', text: item.detail }) : null,
    item.fix ? h('span', { class: 'fix', text: item.fix }) : null);
}

function waiting(text) {
  return h('li', { class: 'check wait' }, h('span', { class: 'mark' }, h('span', { class: 'spinner' })), h('span', { class: 'what', text }));
}

async function runCheck() {
  const summary = $('#check-summary');
  summary.hidden = true;
  $('#check-list').replaceChildren(skeleton(6));
  const response = await api('/api/presenter/check', { timeout: 60000 });
  if (!response.ok) {
    $('#check-list').replaceChildren(h('li', { class: 'check fail' }, h('span', { class: 'mark' }, icon('x')), h('span', { class: 'what', text: failure(response).text }),
      h('span', { class: 'fix', text: 'The app could not run the check. Reload the page, or look at the bank-web logs.' })));
    return;
  }
  const { items, ready, ms } = response.data;
  const toCheck = items.filter((item) => item.status === 'warn').length;
  const list = h('ul', { class: 'checks-list', 'aria-label': 'Check results' });
  const nodes = [];
  for (const [group, name] of GROUPS) {
    const rows = items.filter((item) => item.group === group);
    if (!rows.length) continue;
    nodes.push(h('li', { class: 'group-label', text: name }), ...rows.map(row));
  }
  list.append(...nodes);
  $('#check-list').replaceChildren(list);
  const words = !ready ? 'Not ready' : toCheck ? `Ready, ${toCheck} to check` : 'Ready';
  summary.className = `chip ${!ready ? 'fail' : toCheck ? 'warn' : 'ok'}`;
  summary.replaceChildren(icon(!ready ? 'x' : toCheck ? 'alert' : 'check', 'sm'), h('span', { text: words }));
  summary.title = `The check took ${duration(ms)}`;
  summary.hidden = false;
  say(words);
}

async function runWarmUp() {
  $('#warm-list').replaceChildren(waiting('Warming up the models, the guard rails and Ace'));
  const response = await api('/api/presenter/warmup', { method: 'POST', timeout: 300000 });
  $('#warm-list').replaceChildren(...(response.ok
    ? response.data.steps.map((step) => row({ ...step, group: 'platform' }))
    : [h('li', { class: 'check fail' }, h('span', { class: 'mark' }, icon('x')), h('span', { class: 'what', text: failure(response).text }))]));
}

/* The button says Pause or Resume: that is the state. A line says it only when the traffic is neither running nor paused. */
function showTraffic(data) {
  const paused = Boolean(data.paused);
  const phase = data.status && data.status.state;
  const button = $('#presenter-traffic');
  button.replaceChildren(icon(paused ? 'play' : 'pause'), h('span', { text: paused ? 'Resume traffic' : 'Pause traffic' }));
  button.dataset.action = paused ? 'resume' : 'pause';
  $('#traffic-state').textContent = paused || !phase || phase === 'running' ? '' : TRAFFIC_STATES[phase] || phase;
}

async function loadTraffic() {
  const response = await api('/api/presenter/traffic');
  if (response.ok) showTraffic(response.data);
  else $('#traffic-state').textContent = failure(response).text;
}

async function toggleTraffic() {
  const action = $('#presenter-traffic').dataset.action || 'pause';
  const response = await api('/api/presenter/traffic', { method: 'POST', body: { action } });
  if (response.ok) { showTraffic(response.data); toast(action === 'pause' ? 'Traffic paused.' : 'Traffic resumed.'); }
  else toast(failure(response).text, 'error');
}

function showReset(data) {
  const part = (label, result) => row({ label, group: 'platform', status: result.ok ? 'ok' : 'fail', detail: result.ok ? '' : result.detail });
  $('#reset-list').replaceChildren(part('Balances and cards', data.bank), part('Traffic counters', data.traffic));
}

export function initPresenter() {
  const buttons = ['#presenter-check', '#presenter-warm', '#presenter-reset', '#presenter-traffic'].map((s) => $(s));
  $('#presenter-check').addEventListener('click', () => whileBusy(buttons, runCheck));
  $('#presenter-warm').addEventListener('click', () => whileBusy(buttons, runWarmUp));
  $('#presenter-reset').addEventListener('click', () => whileBusy(buttons, async () => { const data = await startOver(); if (data) showReset(data); }));
  $('#presenter-traffic').addEventListener('click', () => whileBusy(buttons, toggleTraffic));
  bus.on('view', (view) => { if (view === 'presenter') loadTraffic(); });
  bus.on('bank-reset', showReset);
}

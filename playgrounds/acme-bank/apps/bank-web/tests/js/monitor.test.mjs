/* The monitor of Teams and Developers: one element, which moves between the inspector (docked beside the stage) and a band over the answers
   (where the inspector is not beside the stage), and is hidden on the views that have none. */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { installDom } from './dom-stub.mjs';

const page = installDom({ ids: ['monitor', 'team-monitor', 'dev-monitor', 'band-teams', 'band-developers', 'inspector', 'behind'], media: { '(min-width: 1280px)': true } });
page.ids.inspector.append(page.ids.behind, page.ids.monitor);
page.ids.monitor.append(page.ids['team-monitor'], page.ids['dev-monitor']);
const { bus } = await import('../../static/js/dom.js');
const { state } = await import('../../static/js/store.js');
const { initMonitor, placeMonitor } = await import('../../static/js/monitor.js');
const { DOCKED } = await import('../../static/js/store.js');
initMonitor();

const view = (name) => { state.view = name; bus.emit('view', name); };

test('on the Assistant and the Presenter there is no monitor', () => {
  view('assistant');
  assert.equal(page.ids.monitor.hidden, true);
  view('presenter');
  assert.equal(page.ids.monitor.hidden, true);
});

test('docked, it is the top of the inspector over Behind the answer, and each view shows its own', () => {
  view('teams');
  assert.equal(page.ids.monitor.hidden, false);
  assert.equal(page.ids.inspector.firstElementChild, page.ids.monitor);
  assert.equal(page.ids['team-monitor'].hidden, false);
  assert.equal(page.ids['dev-monitor'].hidden, true);
  assert.equal(page.ids.monitor.classList.contains('band'), false);
  view('developers');
  assert.equal(page.ids['team-monitor'].hidden, true);
  assert.equal(page.ids['dev-monitor'].hidden, false);
  assert.equal(page.ids.inspector.firstElementChild, page.ids.monitor);
});

test('where the inspector is not beside the stage the monitor is the band over the answers of the view, moved and not copied', () => {
  page.setMedia('(min-width: 1280px)', false);
  assert.equal(DOCKED.matches, false);
  view('teams');
  assert.equal(page.ids['band-teams'].firstElementChild, page.ids.monitor);
  assert.equal(page.ids.monitor.classList.contains('band'), true);
  view('developers');
  assert.equal(page.ids['band-developers'].firstElementChild, page.ids.monitor);
  assert.equal(page.ids['band-teams'].children.length, 0, 'it left the first band');
  assert.equal(page.ids.monitor.querySelectorAll('#team-monitor').length, 1, 'one element');
});

test('a screen that grows to the docked width takes it back to the inspector', () => {
  page.setMedia('(min-width: 1280px)', true);
  assert.equal(page.ids.inspector.firstElementChild, page.ids.monitor);
  assert.equal(page.ids.monitor.classList.contains('band'), false);
  assert.equal(page.ids['band-developers'].children.length, 0);
  placeMonitor();
  assert.equal(page.ids.inspector.children.filter((c) => c === page.ids.monitor).length, 1);
});

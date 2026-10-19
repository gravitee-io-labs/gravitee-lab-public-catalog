/* Which view shows, the commands' own edge control, the skip links (they move the focus and nothing else) and the history: framed by the Lab UI the page never
   adds an entry to it. Run over a small DOM. */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { Ev, installDom } from './dom-stub.mjs';

const page = installDom({ ids: ['shell', 'main', 'rail', 'inspector'], media: { '(max-width: 639px)': false, '(min-width: 1280px)': false } });
const { h, bus } = await import('../../static/js/dom.js');
const { initRouter, show, go, railWanted } = await import('../../static/js/router.js');
const { state } = await import('../../static/js/store.js');

const views = ['assistant', 'teams', 'developers', 'presenter'];           // the Commands tab of a phone is the rail itself: it has no section of its own
for (const view of views) page.body.append(h('section', { class: 'view', id: `view-${view}`, 'data-view': view }, h('h1', { id: `h-${view}` }, view)));
page.ids.rail.append(h('h2', { id: 'rail-title' }, 'Commands'));
const skipMain = h('a', { class: 'skip', href: '#main' }, 'Skip to content');
const skipRail = h('a', { class: 'skip', href: '#rail' }, 'Skip to the commands');
const skipInspector = h('a', { class: 'skip', href: '#inspector' }, 'Skip to Behind the answer');
const navTeams = h('a', { class: 'nav-link', href: '#teams', 'data-view': 'teams' }, 'Teams');
const navAssistant = h('a', { class: 'nav-link', href: '#assistant', 'data-view': 'assistant' }, 'Assistant');
page.body.append(skipMain, skipRail, skipInspector, navTeams, navAssistant);
for (const id of ['rail', 'main', 'inspector']) page.ids[id].tabIndex = -1;

/* What the history is told: every entry a page can add (pushState, a new hash) and every replacement. */
const entries = { pushed: 0, replaced: [], hashes: [] };
let hash = '#teams';
Object.defineProperty(globalThis.location, 'hash', { get: () => hash, set: (value) => { entries.hashes.push(value); hash = value; }, configurable: true });
globalThis.history.pushState = () => { entries.pushed += 1; };
globalThis.history.replaceState = (_state, _title, url) => { entries.replaced.push(String(url)); hash = String(url).replace(/^.*(?=#)/, ''); };

initRouter();
const fromOutside = (value) => { hash = value; page.fire('window', 'hashchange'); };       // what the browser does for its own Back or a typed address
const shown = () => (page.ids.shell.dataset.view === 'commands' ? ['commands'] : views.filter((v) => page.doc.getElementById(`view-${v}`).hidden === false));

test('standalone the commands start open: a first visit sees them', () => {
  assert.equal(page.ids.shell.dataset.rail, 'open');
  assert.equal(state.railOpen, true);
  assert.equal(page.stored['acme-bank.rail'], undefined, 'a default is no choice: nothing is kept');
});

test('the address says the view, and an address that is no view shows the assistant', () => {
  assert.deepEqual(shown(), ['teams']);
  assert.equal(page.ids.shell.dataset.view, 'teams', 'the frame knows which view it holds: the commands are beside two of them only');
  fromOutside('#nonsense');
  assert.deepEqual(shown(), ['assistant']);
});

test('"Commands" is a view of a phone only: where the commands are beside the conversation the address shows the assistant', () => {
  fromOutside('#commands');
  assert.deepEqual(shown(), ['assistant']);
  page.setMedia('(max-width: 639px)', true);
  fromOutside('#commands');
  assert.deepEqual(shown(), ['commands']);
  assert.equal(page.ids.shell.dataset.view, 'commands');
  page.setMedia('(max-width: 639px)', false);
  assert.deepEqual(shown(), ['assistant'], 'the phone turned into a laptop: the tab has no place any more');
});

test('"Skip to content" focuses the main part and leaves the view and the address as they are', () => {
  go('teams');
  const click = new Event('click');
  skipMain.dispatchEvent(click);
  assert.equal(click.defaultPrevented, true, 'the link does not change the address');
  assert.deepEqual(shown(), ['teams'], 'a person on Teams stays on Teams');
  assert.equal(page.focused(), page.ids.main);
  assert.equal(hash, '#teams');
  skipInspector.dispatchEvent(new Event('click'));
  assert.equal(page.focused(), page.ids.inspector, 'and so does the link to Behind the answer');
  assert.deepEqual(shown(), ['teams']);
});

test('"Skip to the commands" focuses the commands, and shows them if they were a strip, without making it a choice', () => {
  go('teams');
  bus.emit('rail', false);
  assert.equal(page.ids.shell.dataset.rail, 'closed');
  assert.equal(page.stored['acme-bank.rail'], 'false', 'a person closed them: that is kept');
  skipRail.dispatchEvent(new Event('click'));
  assert.equal(page.ids.shell.dataset.rail, 'open');
  assert.equal(page.focused(), page.ids.rail);
  assert.equal(page.stored['acme-bank.rail'], 'false', 'the strip opened for the skip link: the choice is as it was');
  assert.deepEqual(shown(), ['teams'], 'the view did not change');
  bus.emit('rail', true);
});

test('on a phone "Skip to the commands" goes to the Commands tab and focuses its heading', () => {
  page.setMedia('(max-width: 639px)', true);
  go('developers');
  skipRail.dispatchEvent(new Event('click'));
  assert.deepEqual(shown(), ['commands']);
  assert.equal(page.focused(), page.ids.rail.querySelector('h2'));
  page.setMedia('(max-width: 639px)', false);
});

test('the commands start open at every width unless the person chose, and a choice is kept', () => {
  delete page.stored['acme-bank.rail'];
  assert.equal(railWanted(), true, 'a first visit sees the commands, at 1180 px too: Behind the answer is a sheet there');
  bus.emit('rail', false);
  assert.equal(railWanted(), false, 'a person who closed them keeps them closed');
  assert.equal(page.ids.shell.dataset.rail, 'closed');
  bus.emit('rail', true);
  assert.equal(railWanted(), true);
});

test('framed by the Lab UI the commands start as the slim strip, because the guide runs them; each mode keeps its own choice of the person, and a choice wins over the default', () => {
  delete page.stored['acme-bank.rail'];
  delete page.stored['acme-bank.rail-in-lab'];
  globalThis.window.parent = {};
  assert.equal(railWanted(), false, 'no choice, framed: the strip');
  page.stored['acme-bank.rail'] = 'true';
  assert.equal(railWanted(), false, 'a choice made in a tab of its own does not decide for the Lab UI: the page has one origin in both modes');
  page.stored['acme-bank.rail-in-lab'] = 'true';
  assert.equal(railWanted(), true, 'the person opened them in the Lab UI: they stay open there');
  globalThis.window.parent = globalThis.window;
  assert.equal(railWanted(), true, 'and standalone it is the other choice, which is open');
  page.stored['acme-bank.rail'] = 'false';
  assert.equal(railWanted(), false, 'the person closed them in a tab of their own: closed there');
  delete page.stored['acme-bank.rail'];
  delete page.stored['acme-bank.rail-in-lab'];
  assert.equal(railWanted(), true, 'no choice, standalone: open');
});

test('a skip link is offered only where its place is: the commands beside the Assistant and Teams or in the tab of a phone, Behind the answer where it is docked', () => {
  const offered = () => ({ main: !skipMain.hidden, rail: !skipRail.hidden, inspector: !skipInspector.hidden });
  go('teams');
  assert.deepEqual(offered(), { main: true, rail: true, inspector: false }, 'below 1280 px Behind the answer is a sheet, not a place to skip to');
  page.setMedia('(min-width: 1280px)', true);
  assert.deepEqual(offered(), { main: true, rail: true, inspector: true });
  go('presenter');
  assert.deepEqual(offered(), { main: true, rail: false, inspector: false }, 'the Presenter has neither');
  go('developers');
  assert.deepEqual(offered(), { main: true, rail: false, inspector: true });
  page.setMedia('(max-width: 639px)', true);
  assert.deepEqual(offered(), { main: true, rail: false, inspector: false }, 'a phone: the commands are a tab, and Behind the answer a sheet');
  go('commands');
  assert.deepEqual(offered(), { main: true, rail: true, inspector: false });
  page.setMedia('(max-width: 639px)', false);
  page.setMedia('(min-width: 1280px)', false);
  go('assistant');
});

test('the addresses of the skip links are no views, whoever sets them', () => {
  go('presenter');
  for (const value of ['#main', '#rail', '#inspector']) {
    fromOutside(value);
    assert.deepEqual(shown(), ['presenter'], value);
  }
});

test('a command that goes to a view does not move the focus; a link chosen by the person moves it to the heading', () => {
  const before = page.focused();
  go('assistant');
  assert.equal(page.focused(), before, 'a command changes the view and leaves the focus');
  go('teams', { focus: true });
  assert.equal(page.focused(), page.doc.getElementById('h-teams'));
  assert.equal(state.view, 'teams');
});

test('the tab says the view', () => {
  show('presenter');
  assert.equal(document.title, 'Presenter · ACME Bank');
  show('assistant');
  assert.equal(document.title, 'ACME Bank');
});

test('the page changes the view for a command by replacing the address, never by adding one', () => {
  go('presenter');
  entries.pushed = 0;
  entries.replaced.length = 0;
  entries.hashes.length = 0;
  go('teams');
  go('assistant');
  assert.deepEqual(entries.replaced, ['#teams', '#assistant']);
  assert.deepEqual([entries.pushed, entries.hashes], [0, []]);
});

test('standalone a link to a view is a link: the browser follows it and its Back goes back between views', () => {
  globalThis.window.parent = globalThis.window;
  const click = new Ev('click', { target: navTeams, button: 0 });
  page.doc.dispatchEvent(click);
  assert.equal(click.defaultPrevented, false);
});

test('framed by the Lab UI a link to a view changes the address in place: the history has no entry the Back of another frame could undo', () => {
  globalThis.window.parent = {};
  entries.pushed = 0;
  entries.replaced.length = 0;
  entries.hashes.length = 0;
  go('assistant');
  entries.replaced.length = 0;
  for (const [link, view] of [[navTeams, 'teams'], [navAssistant, 'assistant'], [navTeams, 'teams']]) {
    const click = new Ev('click', { target: link, button: 0 });
    page.doc.dispatchEvent(click);
    assert.equal(click.defaultPrevented, true, 'the browser does not follow it: following it adds an entry');
    assert.deepEqual(shown(), [view]);
  }
  assert.deepEqual(entries.replaced, ['#teams', '#assistant', '#teams']);
  assert.deepEqual([entries.pushed, entries.hashes], [0, []], 'nothing was pushed and no hash was set: a hash that is set is an entry');
});

test('framed, a click that opens a link in another tab or window, or one that a control already took, is left to the browser or to that control', () => {
  globalThis.window.parent = {};
  for (const extra of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { button: 1 }]) {
    const click = new Ev('click', { target: navTeams, button: 0, ...extra });
    page.doc.dispatchEvent(click);
    assert.equal(click.defaultPrevented, false, JSON.stringify(extra));
  }
  const skipped = new Event('click');
  skipRail.dispatchEvent(skipped);
  assert.equal(skipped.defaultPrevented, true, 'a skip link is taken by its own handler, which changes no address');
  globalThis.window.parent = globalThis.window;
});

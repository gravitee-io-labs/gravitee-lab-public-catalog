/* The header holds what is global: the theme menu (and on a phone the way into Gamma with it). The person and the gateway are the head of the
   conversation's (asking.js), over the same small DOM. */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { Ev, installDom } from './dom-stub.mjs';

const page = installDom({ ids: ['topbar', 'gamma-link', 'theme', 'more', 'theme-menu', 'person', 'person-button', 'person-menu', 'person-name', 'person-role', 'person-avatar',
  'open-tokens'] });
const { h, bus } = await import('../../static/js/dom.js');
const store = await import('../../static/js/store.js');
const { initHeader } = await import('../../static/js/header.js');
const { initAsking } = await import('../../static/js/asking.js');

const tools = h('div', { class: 'tools' });
page.body.append(tools);
tools.append(page.ids.theme, page.ids.more, page.ids['theme-menu']);
page.ids['theme-menu'].hidden = true;
for (const id of ['theme', 'more', 'person-button', 'open-tokens']) page.ids[id].tag = 'button';
page.ids['person-menu'].hidden = true;
page.ids.person.append(page.ids['person-button'], page.ids['person-menu']);
page.ids['gamma-link'].tag = 'a';
const control = h('div', { id: 'gateway', role: 'radiogroup' },
  h('button', { type: 'button', role: 'radio', 'aria-checked': 'false', 'data-mode': 'off', class: 'gateway-option' }, 'Direct'),
  h('button', { type: 'button', role: 'radio', 'aria-checked': 'true', 'data-mode': 'on', class: 'gateway-option' }, 'Through the Gravitee gateway'));
page.body.append(control);
store.state.personas = [{ id: 'alice', name: 'Alice Martin', role: 'customer' }, { id: 'tina', name: 'Tina Torres', role: 'teller' }];
store.state.persona = store.state.personas[0];
store.state.config = { gamma_url: 'http://gamma.test', pages: {} };
initHeader();
initAsking();
const key = (menu, name) => menu.dispatchEvent(Object.assign(new Ev('keydown'), { key: name }));

test('the theme menu has three choices, System, Light and Dark, and the one that holds is checked', () => {
  const menu = page.ids['theme-menu'];
  page.ids.theme.click();
  assert.equal(menu.hidden, false);
  assert.equal(page.ids.theme.getAttribute('aria-expanded'), 'true');
  const items = menu.querySelectorAll('.menu-item');
  assert.deepEqual(items.map((item) => item.textContent), ['System', 'Light', 'Dark']);
  assert.deepEqual(items.map((item) => item.getAttribute('aria-checked')), ['true', 'false', 'false']);
  assert.equal(page.focused(), items[0]);
  items[2].click();
  assert.equal(menu.hidden, true);
  assert.equal(page.doc.documentElement.getAttribute('data-theme'), 'dark');
  assert.equal(page.stored['acme-bank.theme'], 'dark');
  assert.equal(page.focused(), page.ids.theme, 'the focus goes back to the button');
  page.ids.theme.click();
  page.ids['theme-menu'].querySelectorAll('.menu-item')[0].click();
  assert.equal(page.doc.documentElement.getAttribute('data-theme'), null, 'System leaves it to the system');
  assert.equal(page.stored['acme-bank.theme'], undefined);
});

test('on a phone the menu button carries the way into Gamma too, and it opens in a new tab', () => {
  page.ids.more.click();
  const menu = page.ids['theme-menu'];
  const gamma = menu.querySelector('a.menu-item');
  assert.equal(gamma.getAttribute('href'), 'http://gamma.test');
  assert.equal(gamma.getAttribute('target'), '_blank');
  assert.equal(gamma.hasAttribute('data-gamma'), true, 'in the Lab UI it opens its tab of Gamma, not a browser tab');
  assert.match(menu.textContent, /Open Gamma.*Theme/s);
  key(menu, 'Escape');
  assert.equal(menu.hidden, true);
  assert.equal(page.focused(), page.ids.more);
  page.ids.theme.click();
  assert.equal(menu.querySelector('a.menu-item'), null, 'on a screen the way into Gamma is the header\'s own button');
  key(menu, 'Escape');
});

test('the arrows move along the theme items, wrapping, and a click elsewhere closes the menu', () => {
  const menu = page.ids['theme-menu'];
  page.ids.theme.click();
  const first = page.focused();
  key(menu, 'ArrowDown');
  assert.notEqual(page.focused(), first);
  key(menu, 'ArrowUp');
  key(menu, 'ArrowUp');
  assert.match(page.focused().textContent, /Dark/, 'wraps to the last item');
  page.doc.dispatchEvent(Object.assign(new Ev('click'), { target: page.body }));
  assert.equal(menu.hidden, true);
});

test('the person menu opens on a click, the focus goes to who is signed in, Escape gives it back', () => {
  const button = page.ids['person-button'];
  const menu = page.ids['person-menu'];
  button.click();
  assert.equal(menu.hidden, false);
  assert.equal(button.getAttribute('aria-expanded'), 'true');
  assert.match(page.focused().textContent, /Alice Martin/);
  key(menu, 'ArrowDown');
  assert.match(page.focused().textContent, /Tina Torres/);
  key(menu, 'ArrowDown');
  assert.match(page.focused().textContent, /Sign out/);
  key(menu, 'Escape');
  assert.equal(menu.hidden, true);
  assert.equal(page.focused(), button);
  button.click();
  key(menu, 'Tab');
  assert.equal(menu.hidden, true);
});

test('the person is said once, in the head of the conversation: first name and role, the whole name to a screen reader, and "Choose who is asking" when nobody is', () => {
  assert.equal(page.ids['person-name'].textContent, 'Alice');
  assert.equal(page.ids['person-role'].textContent, 'customer');
  assert.match(page.ids['person-button'].getAttribute('aria-label'), /^Alice Martin, customer\./);
  assert.equal(page.ids['open-tokens'].disabled, false);
  store.state.persona = null;
  bus.emit('persona');
  assert.equal(page.ids['person-name'].textContent, 'Choose who is asking');
  assert.equal(page.ids.person.classList.contains('open-question'), true, 'the selector is the call to action');
  assert.equal(page.ids['open-tokens'].disabled, true);
  page.ids['person-button'].click();
  assert.equal(page.ids['person-menu'].querySelectorAll('.menu-item').some((item) => /Sign out/.test(item.textContent)), false, 'nobody is signed in: nothing to sign out of');
  page.ids['person-button'].click();
  store.state.persona = store.state.personas[0];
  bus.emit('persona');
});

test('choosing the other route switches the control and the route', () => {
  const [direct, through] = control.querySelectorAll('.gateway-option');
  direct.click();
  assert.equal(store.state.gateway, false);
  assert.equal(direct.getAttribute('aria-checked'), 'true');
  assert.equal(through.getAttribute('aria-checked'), 'false');
  through.click();
  assert.equal(store.state.gateway, true);
});

test('the arrows of the gateway control choose the other route and take the focus along', () => {
  const [direct, through] = control.querySelectorAll('.gateway-option');
  through.focus();
  through.dispatchEvent(Object.assign(new Ev('keydown'), { key: 'ArrowLeft' }));
  assert.equal(store.state.gateway, false);
  assert.equal(page.focused(), direct);
  assert.equal(direct.tabIndex, 0);
  assert.equal(through.tabIndex, -1, 'one stop of the keyboard');
  direct.dispatchEvent(Object.assign(new Ev('keydown'), { key: 'ArrowRight' }));
  assert.equal(store.state.gateway, true);
});

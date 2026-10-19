/* The head of the conversation holds what governs it: how the question reaches Ace, at the left with Ace, and at the right end, as on any site that has an account,
   the person's own token and who is asking. They sit where the person acts, not in the header of the app. */
import { $, $$, h, bus, initials } from './dom.js';
import { icon } from './icons.js';
import { state } from './store.js';
import { choose, signOut } from './session.js';
import { copyText } from './clipboard.js';
import { menuOf } from './menus.js';
import { say } from './ui.js';

export function avatar(persona, size = '') {
  return h('span', { class: `avatar ${persona ? persona.id : 'avatar-empty'} ${size}`.trim() },
    persona ? initials(persona.name) : icon('user'));
}

/* ---- the gateway: the question goes through it, or straight to Ace ------------------------------------------------------ */

function setGateway(on) {
  state.gateway = on;
  for (const option of $$('.gateway-option')) option.setAttribute('aria-checked', String((option.dataset.mode === 'on') === on));
}

function initGateway() {
  const options = $$('.gateway-option');
  const syncTabindex = () => { for (const option of options) option.tabIndex = option.getAttribute('aria-checked') === 'true' ? 0 : -1; };
  for (const option of options) {
    option.addEventListener('click', () => { setGateway(option.dataset.mode === 'on'); syncTabindex(); });
    option.addEventListener('keydown', (event) => {
      const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
      if (!step) return;
      event.preventDefault();
      const next = options[(options.indexOf(option) + step + options.length) % options.length];
      setGateway(next.dataset.mode === 'on');
      syncTabindex();
      next.focus();
    });
  }
  syncTabindex();
}

/* ---- the person ---------------------------------------------------------------------------------------------------------- */

function renderPerson() {
  const who = state.persona;
  $('#person-name').textContent = who ? who.name.split(' ')[0] : 'Choose who is asking';          // the first name: the whole name is in the menu and said by the button
  $('#person-role').textContent = who ? who.role : '';
  $('#person-avatar').replaceWith(Object.assign(avatar(who), { id: 'person-avatar' }));
  $('#person-button').setAttribute('aria-label', who ? `${who.name}, ${who.role}. Change who is asking` : 'Choose who is asking');
  $('#person').classList.toggle('open-question', !who);
  $('#open-tokens').disabled = !who;
}

/* A demo user name or password, quiet, with its own button to copy it: the login page of Access Management asks for the password (the user name is filled in). */
function credential(value, what, name) {
  const copy = h('button', { type: 'button', role: 'menuitem', class: 'menu-copy', 'aria-label': `Copy the ${what} of ${name}`, title: `Copy the ${what}`,
    onclick: async () => {
      const done = await copyText(value);
      copy.classList.add(done ? 'done' : 'failed');          // the button's own mark says it (the icon is not replaced: a click that changes its own target is not on the menu)
      say(done ? `${what} copied` : `${what} not copied`);
      setTimeout(() => copy.classList.remove('done', 'failed'), 1400);
    } }, icon('copy', 'sm'), icon('check', 'sm'), icon('alert', 'sm'));
  return h('div', { class: 'menu-cred' }, h('span', { class: 'cred-what', text: what }), h('code', { text: value }), copy);
}

/* One person: the row that chooses them (it says who is signed in: choosing them opens no window), then the user name and the password of their account at Access
   Management. */
function personItem(p, close) {
  const current = !!state.persona && state.persona.id === p.id;
  return h('div', { class: 'menu-person', role: 'none' },
    h('button', { type: 'button', role: 'menuitemradio', class: 'menu-item', 'aria-checked': String(current),
      onclick: () => { close(true); choose(p.id, { focus: true }); } },
    avatar(p), h('span', { class: 'who' }, h('span', { text: p.name }), h('small', { text: state.signed.includes(p.id) ? `${p.role} · signed in` : p.role })),
    current && h('span', { class: 'tick' }, icon('check'))),
    p.username ? credential(p.username, 'username', p.name) : null, p.password ? credential(p.password, 'password', p.name) : null);
}

function initPerson() {
  menuOf({ button: $('#person-button'), menu: $('#person-menu'), home: $('#person'), items: (close) => [
    h('div', { class: 'menu-label', text: 'Sign in at Access Management' }),
    ...state.personas.map((p) => personItem(p, close)),
    ...(state.persona ? [h('hr'), h('button', { type: 'button', role: 'menuitem', class: 'menu-item', onclick: () => { close(true); signOut(); } },
      icon('logout'), h('span', { class: 'who' }, h('span', { text: 'Sign out' })))] : [])] });
  bus.on('persona', renderPerson);
}

export function initAsking() {
  initGateway();
  initPerson();
  renderPerson();
}

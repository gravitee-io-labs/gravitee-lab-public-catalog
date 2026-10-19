/* The header holds what is global and nothing else: the brand, the views, the way into Gamma and the theme. The person, the gateway and
   Tokens belong to the conversation (asking.js), the commands to their own rail. */
import { $, $$, h, safeUrl } from './dom.js';
import { icon } from './icons.js';
import { state } from './store.js';

const SYSTEM_DARK = window.matchMedia('(prefers-color-scheme: dark)');
const BAR = { light: '#f6f5f3', dark: '#0e0d0c' };            // the browser's own bar follows the page (the same as --bg)
const THEMES = [['system', 'System', 'monitor'], ['light', 'Light', 'sun'], ['dark', 'Dark', 'moon']];

/* ---- theme ------------------------------------------------------------------------------------------------------- */

/* The theme the person chose, else nothing (the system decides); and the theme the page shows. */
const chosen = () => document.documentElement.getAttribute('data-theme');
const showing = () => chosen() || (SYSTEM_DARK.matches ? 'dark' : 'light');

function setTheme(theme) {
  if (theme) document.documentElement.setAttribute('data-theme', theme);
  else document.documentElement.removeAttribute('data-theme');
  try {
    if (theme) localStorage.setItem('acme-bank.theme', theme);
    else localStorage.removeItem('acme-bank.theme');
  } catch { /* kept for this visit only */ }
  paintTheme();
}

function paintTheme() {
  const dark = showing() === 'dark';
  const button = $('#theme');
  button.replaceChildren(icon(chosen() ? (dark ? 'moon' : 'sun') : 'monitor'));
  button.setAttribute('aria-label', `Theme: ${chosen() || 'system'}`);
  button.title = `Theme: ${chosen() || 'system'}`;
  for (const bar of $$('meta[name="theme-color"]')) {
    bar.dataset.system = bar.dataset.system || bar.content;
    bar.content = chosen() ? BAR[chosen()] : bar.dataset.system;
  }
}

/* ---- the one menu of the header: the theme on a screen, and with Open Gamma on a phone -------------------------------- */

let opener = null;

function closeMenu(focusOpener = false) {
  const menu = $('#theme-menu');
  if (menu.hidden) return;
  menu.hidden = true;
  for (const button of [$('#theme'), $('#more')]) button.setAttribute('aria-expanded', 'false');
  if (focusOpener && opener) opener.focus();
}

function openMenu(button) {
  const menu = $('#theme-menu');
  opener = button;
  const phone = button === $('#more');
  const now = chosen() || 'system';
  const gamma = safeUrl(state.config.gamma_url);
  menu.replaceChildren(
    ...(phone && gamma ? [h('a', { role: 'menuitem', class: 'menu-item', href: gamma, target: '_blank', rel: 'noopener', 'data-gamma': '', onclick: () => closeMenu() },
      icon('gamma'), h('span', { class: 'who' }, h('span', { text: 'Open Gamma' })), icon('external')), h('hr')] : []),
    h('div', { class: 'menu-label', text: 'Theme' }),
    ...THEMES.map(([id, label, name]) => h('button', {
      type: 'button', role: 'menuitemradio', class: 'menu-item', 'aria-checked': String(now === id),
      onclick: () => { closeMenu(true); setTheme(id === 'system' ? null : id); },
    }, icon(name), h('span', { class: 'who' }, h('span', { text: label })), now === id && h('span', { class: 'tick' }, icon('check')))));
  menu.hidden = false;
  menu.classList.toggle('from-phone', phone);
  button.setAttribute('aria-expanded', 'true');
  ($('[aria-checked="true"]', menu) || $('.menu-item', menu)).focus();
}

function initMenu() {
  for (const button of [$('#theme'), $('#more')]) button.addEventListener('click', () => ($('#theme-menu').hidden ? openMenu(button) : closeMenu()));
  $('#theme-menu').addEventListener('keydown', (event) => {
    const items = $$('.menu-item:not(:disabled)', $('#theme-menu'));
    const at = items.indexOf(document.activeElement);
    if (event.key === 'Escape') { event.preventDefault(); closeMenu(true); }
    else if (event.key === 'ArrowDown') { event.preventDefault(); items[(at + 1) % items.length].focus(); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); items[(at - 1 + items.length) % items.length].focus(); }
    else if (event.key === 'Tab') closeMenu();
  });
  document.addEventListener('click', (event) => { if (!$('.tools').contains(event.target)) closeMenu(); });
}

export function initHeader() {
  const gamma = safeUrl(state.config.gamma_url);
  if (gamma) $('#gamma-link').href = gamma;
  SYSTEM_DARK.addEventListener('change', paintTheme);
  paintTheme();
  initMenu();
  /* What the sticky things below the header must clear: the header's height, or nothing where the header goes with the page (a short screen). */
  const topbar = $('#topbar');
  const measure = () => document.documentElement.style.setProperty('--header-h', getComputedStyle(topbar).position === 'sticky' ? `${topbar.offsetHeight}px` : '0px');
  new ResizeObserver(measure).observe(topbar);
  window.addEventListener('resize', measure);
  measure();
}

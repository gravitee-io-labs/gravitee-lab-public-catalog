/* A menu that a button opens (the person who is asking, the team that calls): the arrows move along its items, Escape and Tab close it, a click
   elsewhere closes it, and the focus goes back to the button. `items()` makes its nodes each time it opens, so it shows what is true then. */
import { $$ } from './dom.js';

const STOPS = '.menu-item:not(:disabled), .menu-copy:not(:disabled)';          // what the arrows move along: the rows, and the buttons that copy

export function menuOf({ button, menu, home = button.parentElement, items }) {
  const close = (focusButton = false) => {
    if (menu.hidden) return;
    menu.hidden = true;
    button.setAttribute('aria-expanded', 'false');
    if (focusButton) button.focus();
  };
  const open = () => {
    menu.replaceChildren(...items(close));
    menu.hidden = false;
    button.setAttribute('aria-expanded', 'true');
    (menu.querySelector('[aria-checked="true"][role="menuitemradio"]') || menu.querySelector('.menu-item')).focus();
  };
  button.addEventListener('click', () => (menu.hidden ? open() : close()));
  menu.addEventListener('keydown', (event) => {
    const stops = $$(STOPS, menu);
    const at = stops.indexOf(document.activeElement);
    if (event.key === 'Escape') { event.preventDefault(); close(true); }
    else if (event.key === 'ArrowDown') { event.preventDefault(); stops[(at + 1) % stops.length].focus(); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); stops[(at - 1 + stops.length) % stops.length].focus(); }
    else if (event.key === 'Tab') close();
  });
  document.addEventListener('click', (event) => { if (!home.contains(event.target)) close(); });
  return { open, close };
}

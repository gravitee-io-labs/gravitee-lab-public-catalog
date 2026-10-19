/* The monitor of Teams and Developers: what is left of the budget, or of the tokens of this minute, with its meter. Beside the stage it is the top
   of the right column, over Behind the answer; where that column is not beside the stage it is a band over the answers, which stays in view while
   they come. It is one element: it moves, it is not copied. */
import { $, bus } from './dom.js';
import { state, DOCKED } from './store.js';

const SLOTS = { teams: '#band-teams', developers: '#band-developers' };

export function placeMonitor() {
  const monitor = $('#monitor');
  const view = state.view;
  const shown = view in SLOTS;
  monitor.hidden = !shown;
  $('#team-monitor').hidden = view !== 'teams';
  $('#dev-monitor').hidden = view !== 'developers';
  if (!shown) return;
  monitor.classList.toggle('band', !DOCKED.matches);
  if (DOCKED.matches) {
    const aside = $('#inspector');
    if (aside.firstElementChild !== monitor) aside.prepend(monitor);
  } else if (monitor.parentElement !== $(SLOTS[view])) {
    $(SLOTS[view]).append(monitor);
  }
}

export function initMonitor() {
  bus.on('view', placeMonitor);
  DOCKED.addEventListener('change', placeMonitor);
  placeMonitor();
}

/* The composer has two modes, a question for Ace and a payment by the person, chosen with a switch in its own toolbar. A payment is a turn of
   the conversation like a question is: the mode only says what the next thing sent is. */
import { $, $$ } from './dom.js';
import { state } from './store.js';

const MODES = ['ask', 'pay'];

function setMode(mode, { focus = true } = {}) {
  if (!MODES.includes(mode) || state.mode === mode) return;
  state.mode = mode;
  const paying = mode === 'pay';
  $('#composer').hidden = paying;
  $('#money-form').hidden = !paying;
  $('#send').hidden = paying;
  $('#money-send').hidden = !paying;
  for (const option of $$('.mode-option')) {
    const on = option.dataset.mode === mode;
    option.setAttribute('aria-checked', String(on));
    option.tabIndex = on ? 0 : -1;
  }
  if (focus) (paying ? $('#money-from') : $('#message')).focus({ preventScroll: true });
}

export function initComposer() {
  const options = $$('.mode-option');
  for (const option of options) {
    option.addEventListener('click', () => setMode(option.dataset.mode));
    option.addEventListener('keydown', (event) => {
      const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
      if (!step) return;
      event.preventDefault();
      const next = options[(options.indexOf(option) + step + options.length) % options.length];
      setMode(next.dataset.mode);
      next.focus();
    });
  }
  /* Escape in the form of a payment goes back to the question. */
  $('#money-form').addEventListener('keydown', (event) => { if (event.key === 'Escape') { event.preventDefault(); setMode('ask'); } });
}

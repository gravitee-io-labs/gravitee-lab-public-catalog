/* Inside the Lab UI (the page is framed) a way into Gamma does not open a browser tab: the page tells the frame's parent where to go,
   and the Lab UI shows it in its own tab of the playground. Standalone nothing changes: the link opens a new tab as it always did.
   Every link or button that opens Gamma says so with `data-gamma` (a link a model wrote has none).
   This module and `actions.js` are all the page has with the Lab UI: it says where to go (here) and that it is ready (there), and it hears the guide's
   actions (there). It never says where the person is, and never hears which page of the guide is read. */
import { bus } from './dom.js';
import { BEAT, GIVE_UP, destination, pause, wordsOf } from './lookup.js';
import { toast } from './ui.js';
import { GAMMA_DOWN } from './words.js';

export const embedded = () => window.parent !== window;

/* Where the Lab UI is, the same two origins as the `frame-ancestors` of security.py (a test holds them equal). What is said to it goes to them, and what is
   heard from it must come from one of them. Where the browser does not say who the parent is (Firefox has no `ancestorOrigins`, and a page may be sent with no
   referrer) a message goes to each of them, and the browser delivers it only where the origin is the parent's. Never to any origin. */
export const LAB_ORIGINS = ['http://localhost:9000', 'http://127.0.0.1:9000'];

function parentOrigins() {
  const ancestors = typeof location !== 'undefined' && location.ancestorOrigins ? location.ancestorOrigins : [];
  if (ancestors.length && ancestors[0] !== 'null') return [ancestors[0]];
  try {
    const referrer = new URL(document.referrer).origin;
    if (referrer && referrer !== 'null') return [referrer];
  } catch { /* no referrer: the Lab UI's own origins */ }
  return LAB_ORIGINS;
}

/* Says something to the Lab UI. */
export function tell(message, parent = window.parent) {
  for (const origin of parentOrigins()) parent.postMessage(message, origin);
}

const SHOW_AFTER = 600;       // ms before the page says it is looking: a lookup that is over sooner needs no notice

/* Where the person is handed over: the address goes to the Lab UI, which shows it in its own tab of the playground (and the sheet over the commands has done its
   job). What the person must be told is said first, in the app: the Gamma tab hides it. Gamma has none of what was asked: the sentence says so, and the
   list that is open instead takes the person away only once it has been read. Gamma did not answer: nothing opens, and the sentence says so. */
async function hand(where, words, { parent = window.parent, sleep = pause } = {}) {
  if (where.state === 'down' || !where.url) {
    toast(GAMMA_DOWN, 'info');
    return;
  }
  if (where.state === 'missing' && words) {
    toast(words.missing, 'info');
    await sleep(BEAT);
  }
  tell({ type: 'gravitee-lab:open', url: where.url }, parent);
  bus.emit('gamma-opened');
}

/* Takes the click of every way into Gamma. The evidence of a call is looked up, for as long as Gamma needs to have it: the link says it is working (dimmed, and
   a notice once it takes a moment), one click is one lookup, and what Gamma does not have is said before the person is taken anywhere. The link stays dimmed
   until the person is handed over, so that a second click does not start a second lookup. */
export function initEmbed() {
  document.addEventListener('click', async (event) => {
    const link = event.target && event.target.closest ? event.target.closest('[data-gamma]') : null;
    if (!link || !embedded()) return;
    event.preventDefault();
    if (link.getAttribute('aria-busy') === 'true') return;
    const href = link.getAttribute('href');
    const words = wordsOf(href);
    let notice = null;
    link.setAttribute('aria-busy', 'true');
    const timer = words ? setTimeout(() => { notice = toast(words.looking, 'info', GIVE_UP); }, SHOW_AFTER) : null;
    const where = await destination(href);
    clearTimeout(timer);
    if (notice) notice();
    await hand(where, words);
    link.removeAttribute('aria-busy');
  }, true);
}

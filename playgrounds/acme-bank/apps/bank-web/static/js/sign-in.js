/* Signing in is Access Management's own login page, in a window of its own: the page opens it from the click that asked (a popup the page opens by itself is
   blocked), the window goes to /login, which sends it on to Access Management, and when the person has typed their password and the server has finished the sign-in,
   the window tells the page and closes itself (sign-in-done.js). The login page can never be shown in a frame, so this is the one way, inside the Lab UI and in a
   tab of its own. The page hears the window and nobody else: the message must come from the origin of this page and from the very window it opened. What the
   message says is only how it ended: who is signed in is read from the server. */
import { SIGN_IN, SIGN_IN_MESSAGE } from './words.js';

/* The window is named, so that a second sign-in goes to the same window and not to another; the name is this page's own, so that a second tab of the app has a window of its
   own and not the first tab's. The size is that of Access Management's login page: its form, and nothing under it. */
const NAME = `acme-bank-sign-in-${Math.random().toString(36).slice(2, 10)}`;
const FEATURES = 'popup,width=660,height=620';
const WATCH = 500;          // ms between two looks at whether the window was closed

/* What the page uses of the browser: a test hands in its own. */
const PORTS = {
  open: (url) => window.open(url, NAME, FEATURES),
  origin: () => location.origin,
  listen: (fn) => window.addEventListener('message', fn),
  stop: (fn) => window.removeEventListener('message', fn),
  every: (fn, ms) => setInterval(fn, ms),
  clear: (timer) => clearInterval(timer),
};

let current = null;          // the sign-in that waits for its window: one at a time

/* Opens the login page for a person and says how the sign-in ended: { ok, outcome }, the outcome one of the server's (words.js) or 'blocked' (the browser did not open
   the window) or 'closed' (the person closed it). Call it from a click, with nothing awaited before. */
export function signInWindow(persona, ports = PORTS) {
  if (current) current('replaced');                      // the named window goes to the new login page: the sign-in it was for is over
  const popup = ports.open(`/login?persona=${encodeURIComponent(persona)}`);
  if (!popup) return Promise.resolve({ ok: false, outcome: 'blocked' });
  if (popup.focus) popup.focus();
  return new Promise((resolve) => {
    let looked = false;
    const end = (outcome) => {
      ports.clear(timer);
      ports.stop(heard);
      if (current === end) current = null;
      resolve({ ok: outcome === 'signed-in', outcome });
    };
    const heard = (event) => {
      if (event.source !== popup || event.origin !== ports.origin()) return;
      const message = event.data;
      if (!message || message.type !== SIGN_IN_MESSAGE) return;
      end(typeof message.outcome === 'string' && Object.hasOwn(SIGN_IN, message.outcome) ? message.outcome : 'failed');
    };
    /* A window that closes itself has told the page first, but the two are not ordered: the page looks twice before it says the person closed it. */
    const timer = ports.every(() => {
      if (!popup.closed) { looked = false; return; }
      if (looked) end('closed');
      looked = true;
    }, WATCH);
    current = end;
    ports.listen(heard);
  });
}

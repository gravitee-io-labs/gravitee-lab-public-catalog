/* The window of a sign-in ends here, after Access Management has sent the browser back and the server has finished the sign-in (or not). It tells the page that
   opened it how it ended, with the address of its own origin as the only target, and closes itself. It says nothing the address could carry away: the address holds
   the outcome and nothing else (the code and the state are used and gone), and the page asks the server who is signed in rather than believe a message. Where no
   page opened this window, or it could not be told, the window stays, says it, and has a way back to the app (a window that closes itself is gone before anybody
   reads it). A static script: the page has no inline script. */
import { SIGN_IN, SIGN_IN_MESSAGE } from './words.js';

/* How the sign-in ended, as the address says it: one of the outcomes the page has a sentence for, else it failed. */
export function outcomeOf(search) {
  const found = new URLSearchParams(search).get('outcome');
  return typeof found === 'string' && Object.hasOwn(SIGN_IN, found) ? found : 'failed';
}

/* `page` is what this window is: its address, what opened it and how it closes. A test hands in its own. */
export function finish(page, text) {
  const outcome = outcomeOf(page.search);
  page.clean();                                  // the outcome is the page's to know, not the history's
  text.textContent = SIGN_IN[outcome];
  if (!page.opener) return outcome;
  page.opener.postMessage({ type: SIGN_IN_MESSAGE, outcome }, page.origin);
  page.close();
  return outcome;
}

if (typeof document !== 'undefined' && document.getElementById('done-text')) {
  finish({
    search: location.search, origin: location.origin, opener: window.opener,
    clean: () => history.replaceState(null, '', location.pathname), close: () => window.close(),
  }, document.getElementById('done-text'));
}

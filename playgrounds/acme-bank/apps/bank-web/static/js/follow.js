/* The page a link of the evidence opens in a tab of its own (a button of the app, outside the Lab UI): the route answers it at
   once, and this looks for the item in Gamma the way the app does inside the Lab UI, then goes there. It says what it is looking for, goes to the list the
   item belongs to (after saying so) when Gamma has none of it, and says when Gamma did not answer, with a way to try again. Nothing is held open for the
   wait, and nothing it says comes from Gamma. A static script: the page has no inline script. */
import { BEAT, destination, pause, wordsOf } from './lookup.js';
import { GAMMA_DOWN, TRY_AGAIN } from './words.js';

const $ = (id) => document.getElementById(id);

/* Looks for the item of the address this page was opened on and goes to it. `go` takes the page to an address; `sleep` is the pause between two looks. */
export async function follow(search, { go = (url) => location.replace(url), sleep = pause, beat = BEAT, now = Date.now } = {}) {
  const href = `/api/evidence${search || ''}`;
  const words = wordsOf(href);
  const text = $('follow-text');
  const say = (sentence) => { text.textContent = sentence; document.title = sentence; };
  $('follow-spinner').hidden = false;
  if (words) say(words.looking);
  const where = await destination(href, { sleep, now });
  if (where.state === 'found' || (where.state === 'missing' && where.url)) {
    if (where.state === 'missing' && words) {
      say(words.missing);
      await sleep(beat);
    }
    go(where.url);
    return where;
  }
  say(GAMMA_DOWN);
  $('follow-spinner').hidden = true;
  const retry = $('follow-retry');
  retry.textContent = TRY_AGAIN;
  retry.hidden = false;
  retry.onclick = () => location.reload();
  retry.focus();
  return where;
}

if (typeof document !== 'undefined' && $('follow-text') && typeof location !== 'undefined' && location.pathname === '/api/evidence') follow(location.search);

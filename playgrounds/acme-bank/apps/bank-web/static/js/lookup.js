/* Looking for the item of a call in Gamma, for the page of the app and for the small page of a tab the browser opened on a link of the evidence.

   The evidence of a call is a route of this app that finds the item in Gamma (its log entry, its trace, its decision, what a run spent). Gamma writes
   the item some seconds after the call: the route says `pending` until it is there, and whoever follows asks again by itself, so that one click is
   one lookup that ends on the item. Nothing else is ever followed: what the route says is an address of Gamma, or it is nothing. */
import { api, safeUrl } from './dom.js';
import { EVIDENCE } from './words.js';

const LOOKUP = '/api/evidence?';
const EVERY = 1500;           // ms between two looks while Gamma has not recorded the call yet
export const GIVE_UP = 45000;        // ms a lookup goes on at most (the app says `missing` by itself some 25 s after the call: this only bounds a page that is told otherwise)
export const BEAT = 2000;            // ms the person has to read that Gamma has none of it before the list that is open instead takes them away

export const isLookup = (href) => typeof href === 'string' && href.startsWith(LOOKUP);
/* Which evidence a link is (trace, logs, decisions, spend), or null. */
export const kindOf = (href) => (isLookup(href) ? new URLSearchParams(href.slice(LOOKUP.length)).get('kind') : null);

/* What a link of the evidence says while it is looked for and when Gamma has none of it, in the words of its kind (null for a link that is not one). */
export const wordsOf = (href) => { const kind = kindOf(href); return Object.hasOwn(EVIDENCE, kind) ? EVIDENCE[kind] : null; };

export const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
/* A page of Gamma the lookup may hand over: an address of Gamma, never one of this app's own routes. */
const gammaPage = (value) => { const href = safeUrl(value); return href && /^https?:/.test(href) ? href : null; };

/* Where a way into Gamma goes: `{ state, url }`. A page of Gamma is `found`. The evidence of a call is looked up: `found` (the item itself), `missing` (Gamma
   has nothing of that call: the list it belongs to, as the way in that is left) or `down` (Gamma did not answer: no address). Never anything else
   is followed: an address that is not one the page may follow is `down`. */
export async function destination(url, { sleep = pause, now = Date.now } = {}) {
  const href = safeUrl(url);
  if (!href) return { state: 'down', url: null };
  if (!isLookup(href)) return { state: 'found', url: href };
  const started = now();
  for (;;) {
    const answer = await api(`${href}&resolve=1`, { timeout: 20000 });
    const { state, url: where } = answer.ok && answer.data ? answer.data : {};
    if ((state === 'found' || state === 'missing') && gammaPage(where)) return { state, url: where };
    if (state !== 'pending' || now() - started >= GIVE_UP) return { state: 'down', url: null };
    await sleep(EVERY);
  }
}

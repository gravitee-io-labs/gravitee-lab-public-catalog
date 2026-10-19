/* Who asks, and who is signed in. A person signs in once, at Access Management's own login page, in a window the page opens (sign-in.js); the server keeps their tokens.
   Choosing somebody who is signed in is instant, choosing somebody else opens the login page. Another person asks, another conversation starts: nothing the one before
   saw or said stays on the screen, and an answer still on its way for the one before is dropped when it arrives (see `state.conversation`). */
import { $, api, bus } from './dom.js';
import { failure } from './errors.js';
import { state } from './store.js';
import { signInWindow } from './sign-in.js';
import { toast } from './ui.js';
import { SIGN_IN, SIGN_IN_WINDOW } from './words.js';

/* What the server says of who asks and who is signed in: `{ persona, signed }`, or nothing for nobody. */
export function adopt(who) {
  const found = state.personas.find((p) => who && p.id === who.persona) || null;
  const changed = (found && found.id) !== (state.persona && state.persona.id);
  state.persona = found;
  state.signed = who && Array.isArray(who.signed) ? who.signed : [];
  if (changed) state.conversation += 1;
  bus.emit('persona', { changed });
  return found;
}

/* A person who is signed in asks now: no login page. */
async function switchTo(id) {
  const response = await api('/api/session', { method: 'POST', body: { persona: id } });
  if (!response.ok) {
    follow(response.data.who);
    toast(failure(response).text, 'error');
    return false;
  }
  adopt(response.data);
  bus.emit('conversation-reset');
  return true;
}

/* A person who is not signed in signs in, at the login page of Access Management, in a window. Called from the click on the person: the window opens before anything is
   awaited. When the window says it is done, the server is asked who is signed in (a message is told, not believed). True when they ask now, false when it did not come to
   that (the person was told: a window the browser blocked has its sentence too). */
async function signInAs(id) {
  const done = await signInWindow(id);
  if (!done.ok) {
    const said = SIGN_IN_WINDOW[done.outcome] || SIGN_IN[done.outcome];
    if (said) toast(said, done.outcome === 'closed' ? 'info' : 'error');
    return false;
  }
  const response = await api('/api/session');
  if (!response.ok) {
    toast(failure(response).text, 'error');
    return false;
  }
  adopt(response.data);
  if (!state.persona || state.persona.id !== id) {          // the window said it was done and the server does not hold it: a message is told, not believed
    toast(SIGN_IN.expired, 'error');
    return false;
  }
  bus.emit('conversation-reset');
  return true;
}

/* A person asks now, whatever it takes: nothing for the one who asks already (their conversation stays), the switch for one who is signed in, the login window for
   one who is not. Only the person control asks this: a command never signs anybody in. */
async function asPerson(id) {
  if (state.persona && state.persona.id === id) return true;
  return state.signed.includes(id) ? switchTo(id) : signInAs(id);
}

/* The person chooses, from the menu, who asks. `focus`: the question box is where they go on. */
export async function choose(id, { focus = false } = {}) {
  const asks = await asPerson(id);
  if (asks && focus) $('#message').focus({ preventScroll: true });
  return asks;
}

/* The tokens of everybody signed in here are forgotten (and the cookie that pointed at them). Access Management keeps its own session: it is not asked to end it, and
   its login page shows its form whatever it knows. */
export async function signOut() {
  const response = await api('/api/session', { method: 'DELETE' });
  adopt(response.ok ? response.data : null);
  bus.emit('conversation-reset');
  toast('Signed out of ACME Bank. Access Management keeps its own session.', 'info');
}

/* A command is for somebody: if they are signed in and are not who asks, they ask now, and the conversation starts again with them. If they are not signed in nothing
   changes: the command goes on with no token, and the gateway says no. */
export async function askAs(id) {
  if (state.signed.includes(id)) await asPerson(id);
}

/* What the server says of who asks after a call, a failure included: the page follows it without clearing the screen, and tells the person when another tab of the
   page (the cookie is shared) chose somebody else. */
export function follow(who) {
  if (!who) return;
  state.signed = Array.isArray(who.signed) ? who.signed : [];
  const before = state.persona;
  if ((who.persona || null) !== (before && before.id)) {
    state.persona = state.personas.find((p) => p.id === who.persona) || null;
    bus.emit('persona', { changed: false });
    if (before && state.persona) toast(`This answer is ${state.persona.name}'s: another tab of this page signed ${state.persona.name} in.`, 'info');
  }
}

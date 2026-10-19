/* What a person is told when a call to the app fails: plain English, with what to do. What only the person who runs the lab needs
   (a container, a model server) is kept apart, as a `hint` the page folds away under "Details". A plain function: tests/js runs it. */

export const SLOW_HINT = 'Is Ollama running? Presenter > Check says what is not ready.';
export const DOWN_HINT = 'Is the bank-web container running? Reload the page when it is.';

/* `response` is what api() gave back: { ok, status, timedOut, aborted, data: { error } }. Returns { text, hint }. */
export function failure(response) {
  const { status, data } = response;
  const said = data && typeof data.error === 'string' ? data.error : '';
  if (response.aborted) return { text: 'You stopped waiting. Ace may still be working: ask again in a moment.', hint: '' };
  if (response.timedOut) return { text: 'No answer came in time. Try again in a minute.', hint: SLOW_HINT };
  if (status === 0) return { text: "Can't reach the bank app. Check your connection, then try again.", hint: DOWN_HINT };
  const bare = !said || /^HTTP \d+$/.test(said);
  return { text: bare ? `Something went wrong (HTTP ${status}). Try again in a minute.` : said, hint: status === 502 || status === 504 ? SLOW_HINT : '' };
}

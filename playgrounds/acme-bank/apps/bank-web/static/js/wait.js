/* What the page says while Ace works: only what it knows, which is how long it has been. A way out comes after a few seconds, and
   after a few more a word on why it can take long. A plain function: tests/js runs it. */

const STOP_AFTER = 5;        // seconds before the person may stop waiting
const SLOW_AFTER = 12;       // seconds before the page says a model on this machine can take a minute

export function waitView(seconds) {
  return { text: `Ace is working - ${seconds} s`, canStop: seconds >= STOP_AFTER, slow: seconds >= SLOW_AFTER };
}

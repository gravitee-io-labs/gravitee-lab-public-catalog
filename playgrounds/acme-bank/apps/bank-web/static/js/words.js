/* The words the page says about the evidence of a call. Plain data, nothing else: the pure modules and the tests import it. */

/* The evidence of a call in Gamma, as its buttons say it: what each opens (its title, on hover), what the page says while it looks for the item (Gamma
   writes it some seconds after the call, and the page asks again by itself), and what it says when Gamma has nothing for the call (the list it belongs to
   opens instead, so the person is never left with nothing). The buttons are in the hop they are about, so "this call" is the one beside them. */
export const EVIDENCE = {
  trace: { title: 'The trace of this call, in Gamma', looking: 'Looking for the trace in Gamma...', missing: 'Gamma has no trace of this call. Its traces are open instead.' },
  logs: { title: 'The log entry of this call, in Gamma', looking: 'Looking for the log in Gamma...', missing: 'Gamma has no log of this call. Its logs are open instead.' },
  decisions: { title: 'The decision about this call, in Gamma', looking: 'Looking for the decision in Gamma...', missing: 'Gamma has no decision for this call. Its decisions are open instead.' },
  spend: { title: 'What the run spent, in Gamma', looking: 'Looking for the spend in Gamma...', missing: 'Gamma has not counted this call. The Spend page is open instead.' },
};

export const GAMMA_DOWN = "Can't open this in Gamma yet. Try again in a few seconds.";
export const TRY_AGAIN = 'Try again';

/* What the window of a sign-in tells the page that opened it (sign-in-done.js says it, sign-in.js hears it). */
export const SIGN_IN_MESSAGE = 'acme-bank:sign-in';

/* How a sign-in at Access Management ended, and what is said of it: by the window that closes itself where nothing opened it, and by the page when the window is gone. */
export const SIGN_IN = {
  'signed-in': 'You are signed in. You can close this window.',
  refused: 'Access Management did not sign you in.',
  expired: 'This sign-in is not valid any more. Choose the person again.',
  other: 'Access Management signed in somebody else than the person you chose. Choose again.',
  stranger: "That account is not one of ACME Bank's three people.",
  failed: 'Access Management did not answer. Try again in a minute.',
};

/* What the page says when the window of a sign-in did not come to an end by itself. */
export const SIGN_IN_WINDOW = {
  blocked: 'The browser blocked the sign-in window. Allow pop-ups for this page, then sign in again.',
  closed: 'The sign-in window was closed before the sign-in was done.',
};

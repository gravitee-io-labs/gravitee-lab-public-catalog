/* Just enough of a browser for the modules of the page that touch one: a window, a document, the storage and fetch. */

export function installPage({ stored = {}, visible = true, fetch = async () => { throw new Error('no fetch'); } } = {}) {
  const listeners = { window: {}, document: {} };
  const on = (target) => (name, fn) => { (listeners[target][name] ||= []).push(fn); };
  const define = (name, value) => Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
  define('window', { matchMedia: () => ({ matches: true, addEventListener() {} }), addEventListener: on('window') });
  define('document', { visibilityState: visible ? 'visible' : 'hidden', addEventListener: on('document') });
  define('localStorage', {
    getItem: (key) => (key in stored ? stored[key] : null),
    setItem: (key, value) => { stored[key] = String(value); },
    removeItem: (key) => { delete stored[key]; },
  });
  define('fetch', fetch);
  return {
    stored,
    fire: (target, name, event) => (listeners[target][name] || []).forEach((fn) => fn(event)),
    hide: () => { globalThis.document.visibilityState = 'hidden'; },
    show: () => { globalThis.document.visibilityState = 'visible'; },
  };
}

/* A fetch that answers each route with what the test says, and keeps what was asked. */
export function fakeFetch(routes) {
  const asked = [];
  const fetch = async (path, options = {}) => {
    asked.push(`${options.method || 'GET'} ${path}`);
    const answer = typeof routes[path] === 'function' ? routes[path]() : routes[path];
    if (answer === undefined) return { ok: false, status: 404, json: async () => ({ error: 'no route' }) };
    return { ok: true, status: 200, json: async () => answer };
  };
  fetch.asked = asked;
  return fetch;
}

export const flush = () => new Promise((resolve) => setImmediate(resolve));

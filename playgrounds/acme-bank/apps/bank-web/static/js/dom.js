/* The small tools every part of the page uses: building nodes (only ever with textContent, so nothing a model or a gateway
   says can become markup), calling the app's API, and writing numbers and times the way the page does. */

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

export function h(tag, props, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') element.className = value;
    else if (key === 'text') element.textContent = value;
    else if (key.startsWith('on')) element.addEventListener(key.slice(2), value);
    else element.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child !== undefined && child !== null && child !== false) element.append(child);
  }
  return element;
}

/* One call to the app. Never throws: a page that cannot reach it says so, a call that takes too long gives up, and a call the person
   stops (`controller.abort()`) says it was stopped. Every call carries the header that says this page made it (the app refuses a GET
   without it). */
export async function api(path, { method = 'GET', body, timeout = 0, controller = new AbortController() } = {}) {
  const options = { method, credentials: 'same-origin', headers: { 'X-Requested-With': 'acme-bank' }, signal: controller.signal };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let timedOut = false;
  const timer = timeout ? setTimeout(() => { timedOut = true; controller.abort(); }, timeout) : null;
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    const aborted = controller.signal.aborted && !timedOut;
    return { ok: false, status: 0, timedOut, aborted,
      data: { error: timedOut ? `No answer after ${Math.round(timeout / 1000)} s` : aborted ? 'Stopped' : 'The app is not answering' } };
  } finally {
    if (timer) clearTimeout(timer);
  }
  let data;
  try {
    data = await response.json();
  } catch {
    data = { error: `HTTP ${response.status}` };
  }
  return { ok: response.ok, status: response.status, data };
}

export const duration = (ms) => (ms === null || ms === undefined ? '' : ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`);
export const count = (n) => (n === null || n === undefined ? '' : n.toLocaleString('en-US'));
/* Dollars with their cents, and four decimals only for a sum under a cent (a few thousand tokens cost that little). */
export const usd = (value) => value.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: value > 0 && value < 0.01 ? 4 : 2 });
/* A link the page may follow: one into Gamma (http), or the route of this app that finds the evidence of a call (/api/evidence). */
export const safeUrl = (url) => (typeof url === 'string' && /^(https?:\/\/|\/api\/evidence\?)/.test(url) ? url : null);
export const initials = (name) => (name || '?').split(/\s+/).map((part) => part[0]).slice(0, 2).join('').toUpperCase();

/* What the browser keeps for the page: a convenience, never a need. Where it refuses, the page works without. */
export const storage = {
  read(key, fallback) {
    try {
      const raw = localStorage.getItem(`acme-bank.${key}`);
      return raw === null ? fallback : JSON.parse(raw);
    } catch { return fallback; }
  },
  write(key, value) {
    try { localStorage.setItem(`acme-bank.${key}`, JSON.stringify(value)); } catch { /* not kept */ }
  },
};

/* A minimal event bus: the parts of the page tell each other what changed without knowing each other. */
const listeners = new Map();
export const bus = {
  on(name, fn) { listeners.set(name, [...(listeners.get(name) || []), fn]); },
  emit(name, detail) { (listeners.get(name) || []).forEach((fn) => fn(detail)); },
};

export const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

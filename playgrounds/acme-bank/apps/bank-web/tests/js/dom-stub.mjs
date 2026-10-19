/* A small DOM that runs this page's modules without a browser; the Lab UI has a stub of its own in lab-ui/tests/js. */

const VOID_FOCUSABLE = new Set(['a', 'button', 'input', 'textarea', 'select', 'summary']);

class Text {
  constructor(text) { this.data = String(text); this.parent = null; }
  get textContent() { return this.data; }
  set textContent(value) { this.data = String(value); }
  get isConnected() { return Boolean(this.parent && this.parent.isConnected); }
  remove() { if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; }
}

const camel = (name) => name.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const dashed = (name) => name.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);

/* ---- selectors: tag#id.class[attr][attr=value][attr^=value]:not(...):first-child:last-child:disabled, with " " and ">" ------------------- */
function compound(source) {
  const parts = [];
  const pattern = /(\*|[a-zA-Z][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:([\^$*]?=)(?:"([^"]*)"|'([^']*)'|([^\]]*)))?\]|:not\(([^)]*)\)|:(first-child|last-child|disabled)/y;
  pattern.lastIndex = 0;
  while (pattern.lastIndex < source.length) {
    const found = pattern.exec(source);
    if (!found) throw new Error(`selector not supported: ${source}`);
    const [, tag, id, cls, attr, op, dq, sq, bare, not, pseudo] = found;
    if (tag) parts.push((el) => tag === '*' || el.tag === tag.toLowerCase());
    else if (id) parts.push((el) => el.id === id);
    else if (cls) parts.push((el) => el.classList.contains(cls));
    else if (attr) {
      const want = dq ?? sq ?? bare;
      parts.push((el) => {
        if (!el.hasAttribute(attr)) return false;
        if (!op) return true;
        const have = el.getAttribute(attr);
        return op === '=' ? have === want : op === '^=' ? have.startsWith(want) : op === '$=' ? have.endsWith(want) : have.includes(want);
      });
    } else if (not !== undefined) { const inner = compound(not); parts.push((el) => !inner(el)); }
    else if (pseudo === 'first-child') parts.push((el) => el.parent && el.parent.children.find((c) => c instanceof El) === el);
    else if (pseudo === 'last-child') parts.push((el) => el.parent && [...el.parent.children].reverse().find((c) => c instanceof El) === el);
    else if (pseudo === 'disabled') parts.push((el) => el.disabled);
  }
  return (el) => parts.every((test) => test(el));
}

function complex(source) {
  const tokens = source.trim().replace(/\s*>\s*/g, ' > ').split(/\s+/);
  const steps = [];
  let combinator = ' ';
  for (const token of tokens) {
    if (token === '>') { combinator = '>'; continue; }
    steps.push({ test: compound(token), combinator });
    combinator = ' ';
  }
  return (el) => {
    const match = (node, index) => {
      if (!steps[index].test(node)) return false;
      if (index === 0) return true;
      if (steps[index].combinator === '>') return node.parent instanceof El && match(node.parent, index - 1);
      for (let up = node.parent; up instanceof El; up = up.parent) if (match(up, index - 1)) return true;
      return false;
    };
    return match(el, steps.length - 1);
  };
}

const selector = (source) => {
  const tests = source.split(/,(?![^(]*\))/).map(complex);
  return (el) => tests.some((test) => test(el));
};

/* ---- events --------------------------------------------------------------------------------------------------------------------------- */
class Target {
  constructor() { this.listeners = {}; }
  addEventListener(type, fn, options) { (this.listeners[type] ||= []).push({ fn, capture: options === true || Boolean(options && options.capture) }); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter((l) => l.fn !== fn); }
  dispatchEvent(event) {
    event.target ||= this;
    event.currentTarget = this;
    for (const { fn } of [...(this.listeners[event.type] || [])]) fn.call(this, event);
    return !event.defaultPrevented;
  }
}

export class El extends Target {
  constructor(tag, doc) {
    super();
    this.tag = tag.toLowerCase();
    this.doc = doc;
    this.attrs = new Map();
    this.children = [];
    this.parent = null;
    this.scrolled = [];
    this.focused = 0;
    this.styleValues = {};
    this.style = { setProperty: (k, v) => { this.styleValues[k] = v; }, removeProperty: (k) => { delete this.styleValues[k]; } };
    this.classList = {
      add: (...names) => this._classes(new Set([...this._classes(), ...names])),
      remove: (...names) => this._classes(new Set([...this._classes()].filter((c) => !names.includes(c)))),
      toggle: (name, force) => {
        const has = this._classes().has(name);
        const on = force === undefined ? !has : force;
        this.classList[on ? 'add' : 'remove'](name);
        return on;
      },
      contains: (name) => this._classes().has(name),
    };
    this.dataset = new Proxy({}, {
      get: (_, key) => (this.hasAttribute(`data-${dashed(key)}`) ? this.getAttribute(`data-${dashed(key)}`) : undefined),
      set: (_, key, value) => { this.setAttribute(`data-${dashed(key)}`, value); return true; },
      has: (_, key) => this.hasAttribute(`data-${dashed(key)}`),
    });
  }

  _classes(next) {
    if (next) { this.attrs.set('class', [...next].join(' ')); return next; }
    return new Set((this.attrs.get('class') || '').split(/\s+/).filter(Boolean));
  }
  get className() { return this.attrs.get('class') || ''; }
  set className(value) { this.attrs.set('class', String(value)); }
  get id() { return this.attrs.get('id') || ''; }
  set id(value) { this.attrs.set('id', String(value)); }
  setAttribute(name, value) { this.attrs.set(name, String(value)); }
  getAttribute(name) { return this.attrs.has(name) ? this.attrs.get(name) : null; }
  hasAttribute(name) { return this.attrs.has(name); }
  removeAttribute(name) { this.attrs.delete(name); }

  get hidden() { return this.attrs.has('hidden'); }
  set hidden(value) { if (value) this.attrs.set('hidden', ''); else this.attrs.delete('hidden'); }
  get disabled() { return this.attrs.has('disabled'); }
  set disabled(value) { if (value) this.attrs.set('disabled', ''); else this.attrs.delete('disabled'); }
  get tabIndex() { return this.attrs.has('tabindex') ? Number(this.attrs.get('tabindex')) : VOID_FOCUSABLE.has(this.tag) ? 0 : -1; }
  set tabIndex(value) { this.attrs.set('tabindex', String(value)); }
  get value() { return this.attrs.get('value') ?? this._value ?? ''; }
  set value(value) { this._value = String(value); }
  get open() { return this.attrs.has('open'); }
  set open(value) { if (value) this.attrs.set('open', ''); else this.attrs.delete('open'); }

  get parentElement() { return this.parent instanceof El ? this.parent : null; }
  get parentNode() { return this.parent; }
  get childNodes() { return this.children; }
  get firstChild() { return this.children[0] || null; }
  get lastChild() { return this.children[this.children.length - 1] || null; }
  get firstElementChild() { return this.children.find((c) => c instanceof El) || null; }
  get lastElementChild() { return [...this.children].reverse().find((c) => c instanceof El) || null; }
  get isConnected() { return this === this.doc.documentElement || Boolean(this.parent && this.parent.isConnected); }
  get previousElementSibling() {
    const siblings = this.parent ? this.parent.children.filter((c) => c instanceof El) : [];
    return siblings[siblings.indexOf(this) - 1] || null;
  }
  get offsetParent() {
    for (let node = this; node instanceof El; node = node.parent) if (node.hidden) return null;
    return this.isConnected ? this.parent : null;
  }
  get scrollHeight() { return 0; }
  get clientHeight() { return 0; }
  get offsetHeight() { return 0; }
  getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0, bottom: 0, right: 0 }; }

  get textContent() { return this.children.map((c) => c.textContent).join(''); }
  set textContent(value) { this.replaceChildren(value === '' ? [] : String(value)); }
  get innerText() { return this.textContent; }

  _adopt(nodes) {
    const out = [];
    for (const node of nodes.flat(Infinity)) {
      if (node === null || node === undefined || node === false) continue;
      const item = node instanceof El || node instanceof Text || node instanceof Fragment ? node : new Text(node);
      if (item instanceof Fragment) { out.push(...item.children.splice(0)); continue; }
      if (item.parent) item.remove();
      out.push(item);
    }
    for (const item of out) item.parent = this;
    return out;
  }
  append(...nodes) { this.children.push(...this._adopt(nodes)); }
  prepend(...nodes) { this.children.unshift(...this._adopt(nodes)); }
  replaceChildren(...nodes) {
    const old = this.children.splice(0);
    for (const child of old) child.parent = null;
    this.children.push(...this._adopt(nodes));
    if (this.doc.activeElement && !this.doc.activeElement.isConnected) this.doc.activeElement = null;      // a focused node that left the page loses the focus
  }
  remove() {
    if (this.parent) this.parent.children.splice(this.parent.children.indexOf(this), 1);
    this.parent = null;
    if (this.doc.activeElement && !this.doc.activeElement.isConnected) this.doc.activeElement = null;
  }
  replaceWith(...nodes) {
    const parent = this.parent;
    const at = parent.children.indexOf(this);
    const adopted = parent._adopt(nodes);
    parent.children.splice(at, 1, ...adopted);
    this.parent = null;
    if (this.doc.activeElement && !this.doc.activeElement.isConnected) this.doc.activeElement = null;
  }
  after(...nodes) { const at = this.parent.children.indexOf(this); this.parent.children.splice(at + 1, 0, ...this.parent._adopt(nodes)); }
  before(...nodes) { const at = this.parent.children.indexOf(this); this.parent.children.splice(at, 0, ...this.parent._adopt(nodes)); }
  contains(other) { for (let node = other; node; node = node.parent) if (node === this) return true; return false; }

  matches(source) { return selector(source)(this); }
  closest(source) { const test = selector(source); for (let node = this; node instanceof El; node = node.parent) if (test(node)) return node; return null; }
  querySelectorAll(source) {
    const test = selector(source);
    const out = [];
    const walk = (node) => { for (const child of node.children) if (child instanceof El) { if (test(child)) out.push(child); walk(child); } };
    walk(this);
    return out;
  }
  querySelector(source) { return this.querySelectorAll(source)[0] || null; }

  click() {
    if (this.disabled) return;
    const event = new Ev('click');
    this.dispatchEvent(event);
    if (!event.propagationStopped) this.doc.dispatchEvent(event);          // the click reaches the document, where a menu closes for a click outside it (the ancestors in between are not modelled)
    if (this.tag === 'summary' && this.parent) this.parent.open = !this.parent.open;
  }
  focus() {
    if (this.disabled || !this.isConnected || this.offsetParent === null && this !== this.doc.documentElement) return;
    this.doc.activeElement = this;
    this.focused += 1;
    this.dispatchEvent(new Ev('focus'));
    this.doc.dispatchEvent(new Ev('focusin', { target: this }));
  }
  blur() { if (this.doc.activeElement === this) this.doc.activeElement = null; }
  scrollIntoView(options) { this.scrolled.push(options || {}); }
  scrollTo() {}
  select() {}
  showModal() { this.attrs.set('open', ''); this.modal = true; }
  close() { this.attrs.delete('open'); this.modal = false; this.dispatchEvent(new Ev('close')); }
}

class Fragment { constructor() { this.children = []; } append(...nodes) { for (const node of nodes.flat(Infinity)) if (node !== null && node !== undefined && node !== false) { const item = node instanceof El || node instanceof Text ? node : new Text(node); item.parent = null; this.children.push(item); } } }

export class Ev {
  constructor(type, extra = {}) { this.type = type; this.defaultPrevented = false; Object.assign(this, extra); }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this.propagationStopped = true; }
}

export function installDom({ ids = [], media = {}, stored = {}, fetch = async () => { throw new Error('no fetch'); }, visible = true } = {}) {
  const define = (name, value) => Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
  const doc = Object.assign(new Target(), { activeElement: null, visibilityState: visible ? 'visible' : 'hidden', title: 'ACME Bank' });
  doc.hasFocus = () => !doc.blurred;                      // a test sets `blurred`: the person is in another frame or window
  doc.createElement = (tag) => new El(tag, doc);
  doc.createElementNS = (_ns, tag) => new El(tag, doc);
  doc.createTextNode = (text) => new Text(text);
  doc.createDocumentFragment = () => new Fragment();
  const root = new El('html', doc);
  const body = new El('body', doc);
  root.append(body);
  doc.documentElement = root;
  doc.body = body;
  doc.querySelector = (source) => (selector(source)(root) ? root : root.querySelector(source));
  doc.querySelectorAll = (source) => root.querySelectorAll(source);
  doc.getElementById = (id) => root.querySelector(`#${id}`);
  /* The elements the modules look up by id exist from the start (the page's markup is not parsed here): a test fills them. */
  const made = {};
  for (const id of ids) { const el = doc.createElement('div'); el.id = id; body.append(el); made[id] = el; }

  const queries = new Map();
  const matchMedia = (query) => {
    if (!queries.has(query)) {
      const state = { matches: Boolean(media[query]), listeners: [] };
      const list = new Target();
      Object.defineProperty(list, 'matches', { get: () => state.matches });          // a getter: setMedia changes it for everything that holds the list
      Object.assign(list, { media: query, addEventListener: (type, fn) => state.listeners.push(fn), removeEventListener() {} });
      queries.set(query, { state, list });
    }
    return queries.get(query).list;
  };
  const setMedia = (query, value) => {
    matchMedia(query);
    const { state, list } = queries.get(query);
    state.matches = value;
    for (const fn of state.listeners) fn({ matches: value, media: query, target: list });
  };

  const win = Object.assign(new Target(), { matchMedia, scrollTo() {}, innerWidth: 1280, innerHeight: 800 });
  win.parent = win;                                       // a page that is not framed is its own parent; a test sets another to frame it
  define('window', win);
  define('document', doc);
  define('localStorage', {
    getItem: (key) => (key in stored ? stored[key] : null),
    setItem: (key, value) => { stored[key] = String(value); },
    removeItem: (key) => { delete stored[key]; },
  });
  define('fetch', fetch);
  define('CSS', { escape: (value) => String(value).replace(/[^\w-]/g, (c) => `\\${c}`) });
  define('requestAnimationFrame', (fn) => setTimeout(fn, 0));
  define('ResizeObserver', class { observe() {} disconnect() {} });
  define('location', { hash: '', href: 'http://localhost/' });
  define('history', { replaceState(_s, _t, url) { globalThis.location.hash = String(url).replace(/^.*(?=#)/, ''); } });
  define('navigator', {});
  define('getComputedStyle', () => ({ position: 'static' }));
  define('Event', Ev);

  const fire = (target, type, extra) => (target === 'window' ? win : doc).dispatchEvent(new Ev(type, extra));
  return {
    doc, body, root, ids: made, stored, setMedia, fire,
    hide: () => { doc.visibilityState = 'hidden'; },
    show: () => { doc.visibilityState = 'visible'; },
    /* An element the modules will look up by id, made if it is not there. */
    el: (id, tag = 'div') => { if (!made[id]) { const el = doc.createElement(tag); el.id = id; body.append(el); made[id] = el; } return made[id]; },
    focused: () => doc.activeElement,
  };
}

export const text = (node) => node.textContent.replace(/\s+/g, ' ').trim();
export const flush = () => new Promise((resolve) => setImmediate(resolve));

/* Notices, and the pieces every part of the page draws the same way: the chips, the evidence of a call, a model's answer. */
import { $, $$, h, safeUrl } from './dom.js';
import { icon } from './icons.js';
import { blocks, inline } from './richtext.js';
import { begin } from './store.js';
import { EVIDENCE } from './words.js';

const own = (table, key) => (typeof key === 'string' && Object.hasOwn(table, key) ? table[key] : null);

/* What a screen reader says without being sent anywhere: one polite region for the whole page, written when an answer comes, a wait begins
   or something fails. Cleared first, so that the same words said twice are heard twice. */
export function say(text) {
  const box = $('#announcer');
  if (!box) return;
  box.textContent = '';
  setTimeout(() => { box.textContent = text; }, 60);
}

/* A short notice. It stops while the pointer or the focus is on it, and an error stays until it is closed: a notice that goes away
   by itself is a notice somebody who reads slowly never reads. An error is an alert, the others are said by the announcer. */
export function toast(message, tone = 'ok', ms = 6000) {
  const box = $('#toasts');
  const sticky = tone === 'error';
  let timer = null;
  const close = () => { clearTimeout(timer); item.classList.add('leaving'); setTimeout(() => item.remove(), 220); };
  const start = () => { if (!sticky) timer = setTimeout(close, ms); };
  const pause = () => clearTimeout(timer);
  const item = h('div', { class: `toast ${tone === 'ok' ? '' : tone}`.trim(), role: sticky ? 'alert' : null,
    onmouseenter: pause, onmouseleave: start, onfocusin: pause, onfocusout: start },
  icon(tone === 'error' ? 'alert' : tone === 'info' ? 'info' : 'check'), h('span', { class: 'toast-text', text: message }),
  sticky ? h('button', { type: 'button', class: 'icon-btn toast-close', 'aria-label': 'Close the notice', onclick: close }, icon('x')) : null);
  box.append(item);
  while (box.children.length > 3) box.firstChild.remove();
  if (!sticky) say(message);
  start();
  return close;
}

/* A tag for what a call did or which model answered. The outcomes carry a mark of their own beside the word, so that none of them is told by
   its color alone. */
const CHIP_MARK = { ok: 'check', deny: 'x', fail: 'x', block: 'ban', limit: 'clock', warn: 'alert', error: 'alert', direct: 'shield-off' };
export const chip = (tone, text, extra = '') => h('span', { class: `chip ${tone} ${extra}`.trim() }, CHIP_MARK[tone] ? icon(CHIP_MARK[tone], 'sm') : null, h('span', { text }));

/* The line that opens a disclosure: "Details" with a chevron that turns when it is open. */
export const summaryNode = () => h('summary', {}, icon('chevron-right', 'sm'), h('span', { text: 'Details' }));

/* What only the person who runs the lab needs, folded away. */
export const hintNode = (hint) => (hint ? h('details', { class: 'hint' }, summaryNode(), h('p', { text: hint })) : null);

/* A badge: a small square-cornered label of a hop, under its title. What a call was refused or failed with carries a mark of its own beside the word, so that
   none of them is told by its color alone; `word` is what a screen reader adds to the number it reads ("403", "Denied by policy"). */
const BADGE_MARK = { deny: 'x', block: 'ban', limit: 'clock', error: 'alert', note: 'alert' };
export const badge = (kind, text, { tone = null, word = null, title = null } = {}) => h('span', { class: `badge ${kind} ${tone || ''}`.trim(), title },
  tone && BADGE_MARK[tone] ? icon(BADGE_MARK[tone], 'sm') : null, h('span', { text }), word ? h('span', { class: 'sr', text: ` ${word}` }) : null);

/* What a button of evidence opens, in words: the call beside it, in Gamma. Null for what is not a kind of evidence. */
export function evidenceTitle(item) {
  return Object.hasOwn(EVIDENCE, item.kind) ? EVIDENCE[item.kind].title : null;
}

/* A link to the record of one call in Gamma. Its name says which hop it is of and that it opens Gamma, and its title (on hover) says what it opens. */
function evidenceLink(item, hop) {
  const name = { logs: 'list', decisions: 'scale', trace: 'activity', spend: 'wallet' }[item.kind] || 'external';
  return h('a', { class: 'evidence', href: item.url, target: '_blank', rel: 'noopener', 'data-gamma': '',
    title: evidenceTitle(item), 'aria-label': `${item.label}, ${hop} (opens Gamma)` },
  icon(name, 'sm'), h('span', { text: item.label }));
}

/* The evidence of one call in Gamma, in one fixed order: the person finds Trace where Trace was. Only what exists, and only what is a way into Gamma. */
export const EVIDENCE_ORDER = ['trace', 'logs', 'decisions', 'spend'];
const ordered = (items) => EVIDENCE_ORDER.map((kind) => (Array.isArray(items) ? items : []).find((e) => e && e.kind === kind && safeUrl(e.url))).filter(Boolean);

/* The buttons of one hop, side by side: Trace, Logs, then Decisions or Spend. `hop` is its title. Nothing at all when the call has no evidence. */
export function evidenceButtons(items, hop) {
  const found = ordered(items);
  if (!found.length) return null;
  return h('div', { class: 'hop-evidence', role: 'group', 'aria-label': `Evidence in Gamma, ${hop}` }, found.map((item) => evidenceLink(item, hop)));
}

export function skeleton(rows = 3) {
  return h('div', { 'aria-hidden': 'true' }, Array.from({ length: rows }, () => h('div', { class: 'skeleton row' })));
}

export function empty(iconName, title, text, ...actions) {
  return h('div', { class: 'empty' }, iconName ? icon(iconName) : null, h('strong', { text: title }), text && h('span', { text }), actions.length ? h('div', { class: 'empty-actions' }, actions) : null);
}

/* Disables the buttons while their work runs, so a second press cannot start it twice, and tells the page something is running. */
export async function whileBusy(buttons, work) {
  buttons.forEach((b) => { b.disabled = true; b.setAttribute('aria-busy', 'true'); });
  const done = begin();
  try { return await work(); } finally { done(); buttons.forEach((b) => { b.disabled = false; b.removeAttribute('aria-busy'); }); }
}

/* Where a link a model wrote really leads, written beside its label: a label says what the model wants it to. */
const hostOf = (href) => { try { return new URL(href).host; } catch { return 'unknown address'; } };

const piece = (part) => {
  if (part.type === 'strong') return h('strong', { text: part.text });
  if (part.type === 'code') return h('code', { text: part.text });
  if (part.type === 'link') return h('a', { href: part.href, target: '_blank', rel: 'noopener' }, part.text, h('span', { class: 'host', text: ` (${hostOf(part.href)})` }));
  return part.text;
};
const line = (text) => inline(text).map(piece);

/* A model's answer with the formatting it uses (paragraphs, headings, lists, code, tables, **bold**, `code`, links), built as nodes:
   nothing it says is ever markup, and a link is made only for an http or https address. */
export function richText(text) {
  const out = document.createDocumentFragment();
  for (const block of blocks(text)) {
    if (block.type === 'heading') out.append(h(`h${block.level + 3}`, { class: 'md-heading' }, line(block.text)));
    else if (block.type === 'ul' || block.type === 'ol') out.append(h(block.type, { class: 'md-list' }, block.items.map((item) => h('li', {}, line(item)))));
    else if (block.type === 'code') out.append(h('pre', { class: 'md-code', tabindex: '0', 'aria-label': block.lang ? `Code, ${block.lang}` : 'Code' }, h('code', { text: block.text })));
    else if (block.type === 'table') {
      out.append(h('div', { class: 'md-table', tabindex: '0', role: 'region', 'aria-label': 'Table' }, h('table', {},
        h('thead', {}, h('tr', {}, block.head.map((cell) => h('th', { scope: 'col' }, line(cell))))),
        h('tbody', {}, block.rows.map((row) => h('tr', {}, row.map((cell) => h('td', {}, line(cell)))))))));
    } else out.append(h('p', {}, line(block.text)));
  }
  return out;
}

/* A text that may be long: a few lines, and a button to read the rest where there is more. One inside something closed (a "Details") measures nothing: `remeasure`
   reads it again once it is open. */
export function clamped(text, className = '') {
  const body = h('div', { class: `clamp ${className}`.trim() });
  body.append(richText(text));
  const more = h('button', { type: 'button', class: 'link-button', hidden: true, 'aria-expanded': 'false', onclick: (event) => {
    body.classList.toggle('open');
    const open = body.classList.contains('open');
    event.currentTarget.textContent = open ? 'Show less' : 'Show more';
    event.currentTarget.setAttribute('aria-expanded', String(open));
    event.currentTarget.scrollIntoView({ block: 'nearest' });            // what was opened or closed does not leave its control out of sight
  } }, 'Show more');
  body.measure = () => {
    if (body.classList.contains('open')) return;
    const long = body.scrollHeight > body.clientHeight + 1;
    more.hidden = !long;
    body.classList.toggle('fades', long);
  };
  requestAnimationFrame(body.measure);
  return [body, more];
}

/* Reads again how long the texts inside `root` are (they were closed when they were made). */
export function remeasure(root) {
  for (const body of $$('.clamp', root)) if (body.measure) requestAnimationFrame(body.measure);
}

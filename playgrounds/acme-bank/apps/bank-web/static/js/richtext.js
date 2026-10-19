/* What a model's answer is made of, as plain data: paragraphs, headings, lists, code, tables, and inside a line **bold**, `code` and
   links. A plain function of a string: tests/js runs it. ui.js builds nodes from it (never markup: nothing the model wrote is
   ever read as HTML), and a link is made only for an http or https address.

   An answer is read by the page's own thread, so what it can cost is bounded: only the first MAX_TEXT characters are read (and the answer says
   it was shortened), and a line longer than MAX_LINE is plain text (no pattern is tried on it). Every pattern here is linear on its line. */

export const MAX_TEXT = 20000;         // characters of an answer that are shown
export const MAX_LINE = 2000;          // a longer line is text, whatever it looks like
export const SHORTENED = '(shortened)'; // what an answer cut at MAX_TEXT ends with: the rest is not shown, and Show more cannot reveal it

const FENCE = /^\s*```\s*([\w+-]*)\s*$/;
const HEADING = /^\s{0,3}(#{1,6})\s+(\S.*)$/;
const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBER = /^\s*\d{1,3}[.)]\s+(.*)$/;
const DIVIDER = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const INLINE = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/;
const LINK = /^\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)$/;

const SAFE_LINK = /^https?:\/\/[^\s]+$/i;

const short = (line) => line.length <= MAX_LINE;

/* One line of text as pieces: { type: 'text' | 'strong' | 'code' | 'link', text, href? }. */
function pieces(text) {
  if (!short(text)) return text ? [{ type: 'text', text }] : [];
  const out = [];
  for (const part of text.split(INLINE)) {
    if (!part) continue;
    const link = LINK.exec(part);
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) out.push({ type: 'strong', text: part.slice(2, -2) });
    else if (part.startsWith('`') && part.endsWith('`') && part.length > 2) out.push({ type: 'code', text: part.slice(1, -1) });
    else if (link && SAFE_LINK.test(link[2])) out.push({ type: 'link', text: link[1], href: link[2] });
    else out.push({ type: 'text', text: part });
  }
  return out;
}

/* The text of a paragraph as pieces. The cap is the cap of a line, whatever a paragraph holds: a line of its own past it is plain text, and
   the lines around it keep their bold, code and links. */
export function inline(line) {
  const out = [];
  const add = (piece) => {
    const last = out[out.length - 1];
    if (piece.type === 'text' && last && last.type === 'text') last.text += piece.text;
    else out.push(piece);
  };
  String(line).split('\n').forEach((text, n) => {
    if (n) add({ type: 'text', text: '\n' });
    pieces(text).forEach(add);
  });
  return out;
}

const cells = (line) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim());
const matches = (pattern, line) => short(line) && pattern.test(line);
const startsBlock = (line) => matches(FENCE, line) || matches(HEADING, line) || matches(BULLET, line) || matches(NUMBER, line);
const startsTable = (line, next) => Boolean(next) && short(line) && short(next) && line.includes('|') && next.includes('-') && DIVIDER.test(next);

/* A heading's text without its closing hashes ("## Title ##"), found by looking from the end: no pattern has to give characters back. */
function headingText(text) {
  let end = text.length;
  while (end > 0 && /\s/.test(text[end - 1])) end -= 1;
  let hashes = end;
  while (hashes > 0 && text[hashes - 1] === '#') hashes -= 1;
  if (hashes < end && hashes > 0 && /\s/.test(text[hashes - 1])) {
    end = hashes;
    while (end > 0 && /\s/.test(text[end - 1])) end -= 1;
  }
  return text.slice(0, end);
}

/* The blocks of an answer: { type: 'p', text } | { type: 'heading', level, text } | { type: 'ul' | 'ol', items } |
   { type: 'code', lang, text } | { type: 'table', head, rows }. A fence that is never closed runs to the end. */
export function blocks(text) {
  const all = String(text);
  const clipped = all.length > MAX_TEXT ? `${all.slice(0, MAX_TEXT)}... ${SHORTENED}` : all;
  const lines = clipped.replace(/\r\n?/g, '\n').trim().split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    const fence = short(line) ? FENCE.exec(line) : null;
    if (fence) {
      const body = [];
      i += 1;
      while (i < lines.length && !matches(FENCE, lines[i])) { body.push(lines[i]); i += 1; }
      i += 1;
      out.push({ type: 'code', lang: fence[1], text: body.join('\n') });
      continue;
    }
    const heading = short(line) ? HEADING.exec(line) : null;
    if (heading) { out.push({ type: 'heading', level: Math.min(heading[1].length, 3), text: headingText(heading[2]) }); i += 1; continue; }
    if (startsTable(line, lines[i + 1])) {
      const head = cells(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].includes('|') && lines[i].trim() && short(lines[i])) { rows.push(cells(lines[i])); i += 1; }
      out.push({ type: 'table', head, rows });
      continue;
    }
    const kind = matches(BULLET, line) ? 'ul' : matches(NUMBER, line) ? 'ol' : null;
    if (kind) {
      const pattern = kind === 'ul' ? BULLET : NUMBER;
      const items = [];
      while (i < lines.length && matches(pattern, lines[i])) { items.push(pattern.exec(lines[i])[1]); i += 1; }
      out.push({ type: kind, items });
      continue;
    }
    const body = [];
    while (i < lines.length && lines[i].trim() && !startsBlock(lines[i]) && !startsTable(lines[i], lines[i + 1])) { body.push(lines[i]); i += 1; }
    out.push({ type: 'p', text: body.join('\n') });
  }
  return out;
}

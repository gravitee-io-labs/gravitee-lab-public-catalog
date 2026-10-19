/* The page's icons, drawn here: 24 px strokes in the color of their text. No icon font, no file, nothing fetched. */

const NS = 'http://www.w3.org/2000/svg';
const circle = (x, y, r) => `M${x - r} ${y}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0`;
const shield = 'M12 3 4.5 6v5.5c0 4.5 3 8 7.5 9.5 4.5-1.5 7.5-5 7.5-9.5V6L12 3z';

const ICONS = {
  chat: ['M5 5.5h14A1.5 1.5 0 0 1 20.5 7v8a1.5 1.5 0 0 1-1.5 1.5h-8L6.5 20v-3.5H5A1.5 1.5 0 0 1 3.5 15V7A1.5 1.5 0 0 1 5 5.5z'],
  users: [circle(9, 8, 3.5), 'M2.8 20c.5-3.5 3.1-5.5 6.2-5.5s5.7 2 6.2 5.5', 'M16 4.7a3.5 3.5 0 0 1 0 6.6', 'M18.2 14.8c1.8.7 2.9 2.2 3.2 4.7'],
  code: ['m8 8-4 4 4 4', 'm16 8 4 4-4 4', 'm13.5 5.5-3 13'],
  monitor: ['M3.5 4.5h17v11h-17z', 'M8.5 20h7', 'M12 15.5V20'],
  /* Ace: a small bot, a rounded head with an antenna and two ears, and an A for its face. The one drawing of Ace on the page. */
  ace: ['M7.5 7.5h9a3.5 3.5 0 0 1 3.5 3.5v6a3.5 3.5 0 0 1-3.5 3.5h-9A3.5 3.5 0 0 1 4 17v-6a3.5 3.5 0 0 1 3.5-3.5z', 'M12 7.5V4.6', circle(12, 3.4, 1.1), 'M2 12v3', 'M22 12v3', 'm8.6 17.6 3.4-7.4 3.4 7.4', 'M9.9 15.3h4.2'],
  'shield-off': [shield, 'M4 4l16 16'],
  key: [circle(7.5, 15.5, 3.5), 'm10 13 9.5-9.5', 'm16.5 6.5 2.5 2.5', 'm13.5 9.5 2 2'],
  wrench: ['M14.7 6.3a4 4 0 0 0-5.4 5L3.8 16.8a2 2 0 0 0 2.8 2.8l5.6-5.5a4 4 0 0 0 5-5.4l-2.7 2.7-2.2-.5-.5-2.2 2.7-2.4z'],
  model: ['M6.5 5h11A1.5 1.5 0 0 1 19 6.5v11a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 17.5v-11A1.5 1.5 0 0 1 6.5 5z', 'M9.5 9.5h5v5h-5z', 'M9 2.5V5', 'M15 2.5V5', 'M9 19v2.5', 'M15 19v2.5', 'M2.5 9H5', 'M2.5 15H5', 'M19 9h2.5', 'M19 15h2.5'],
  gateway: ['M4 20V7.5L12 4l8 3.5V20', 'M9.5 20v-5.5h5V20', 'M2.5 20h19'],
  direct: ['M4 12h14', 'm13 7 5 5-5 5'],
  external: ['M14 4h6v6', 'M20 4l-8.5 8.5', 'M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10'],
  sun: [circle(12, 12, 4), 'M12 2.5v2', 'M12 19.5v2', 'M4.9 4.9l1.4 1.4', 'M17.7 17.7l1.4 1.4', 'M2.5 12h2', 'M19.5 12h2', 'M4.9 19.1l1.4-1.4', 'M17.7 6.3l1.4-1.4'],
  moon: ['M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z'],
  send: ['M20.5 3.5 10.5 13.5', 'M20.5 3.5 14 20.5l-3.5-7-7-3.5 17-6.5z'],
  play: ['M8 5v14l11-7L8 5z'],
  check: ['m5 12.5 4.5 4.5L19 7.5'],
  x: ['M6 6l12 12', 'M18 6 6 18'],
  alert: ['M12 4 2.8 19.5h18.4L12 4z', 'M12 10v4.5', 'M12 17.3v.1'],
  info: [circle(12, 12, 8.5), 'M12 11v5', 'M12 7.9v.1'],
  copy: ['M8.5 8.5h11v11h-11z', 'M5 15.5V4.5h11'],
  reset: ['M4 12a8 8 0 1 0 2.4-5.7', 'M4 4v4.5h4.5'],
  'chevron-down': ['m6 9 6 6 6-6'],
  'chevron-right': ['m9 6 6 6-6 6'],
  'chevron-left': ['m15 6-6 6 6 6'],
  user: [circle(12, 8, 4), 'M4.5 20.5c.8-4 4-6 7.5-6s6.7 2 7.5 6'],
  logout: ['M10 4.5H5.5v15H10', 'm15.5 8 4 4-4 4', 'M19.5 12H9'],
  activity: ['M3 12h4l2.5-7 4 14 2.5-7H21'],
  list: ['M8.5 6h12', 'M8.5 12h12', 'M8.5 18h12', 'M4 6h.1', 'M4 12h.1', 'M4 18h.1'],
  scale: ['M12 4v16', 'M7 20h10', 'M5 7.5h14', 'M5 7.5 2.5 13.5a2.8 2.8 0 0 0 5 0L5 7.5z', 'M19 7.5l-2.5 6a2.8 2.8 0 0 0 5 0L19 7.5z'],
  wallet: ['M4 7.5A2.5 2.5 0 0 1 6.5 5H18v3', 'M4 7.5v9A2.5 2.5 0 0 0 6.5 19H20V8H6.5A2.5 2.5 0 0 1 4 7.5z', 'M16 13.5h.1'],
  clock: [circle(12, 12, 8.5), 'M12 7.5V12l3 2'],
  zap: ['M13 3 5 13.5h6L10 21l8-10.5h-6L13 3z'],
  database: ['M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z', 'M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6', 'M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6'],
  pause: ['M8.5 5v14', 'M15.5 5v14'],
  flame: ['M12 3c.8 3.2 5 5.2 5 10a5 5 0 0 1-10 0c0-2 .9-3.2 2-4.2.3 1.4.9 2 1.8 2.2C10.2 8 10.8 5.2 12 3z'],
  gamma: ['M12 3l7.8 4.5v9L12 21l-7.8-4.5v-9L12 3z', 'M12 9.5v5', 'M9.8 10.8 12 12l2.2-1.2'],
  dot: [circle(12, 12, 3)],
  ban: [circle(12, 12, 8.5), 'M6 6l12 12'],
  more: [circle(5.5, 12, 1.2), circle(12, 12, 1.2), circle(18.5, 12, 1.2)],
};

export function icon(name, extra = '') {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', `icon ${extra}`.trim());
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  for (const d of ICONS[name] || ICONS.dot) {
    const path = document.createElementNS(NS, 'path');
    path.setAttribute('d', d);
    svg.append(path);
  }
  return svg;
}

/* The bank's mark: a flat tile and a drawing, both colored by the stylesheet (so a dark page and forced colors have theirs). */
function logo() {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 32 32');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const tile = document.createElementNS(NS, 'rect');
  tile.setAttribute('width', '32'); tile.setAttribute('height', '32'); tile.setAttribute('rx', '9'); tile.setAttribute('class', 'logo-tile');
  const mark = document.createElementNS(NS, 'path');
  mark.setAttribute('d', 'M16 6.5 7 11.5h18L16 6.5zM9.5 13.5v7h2.6v-7H9.5zm5.2 0v7h2.6v-7h-2.6zm5.2 0v7h2.6v-7h-2.6zM7.5 22.5v2h17v-2h-17z');
  mark.setAttribute('class', 'logo-mark');
  svg.append(tile, mark);
  return svg;
}

/* Every <span data-icon="name"> of the page's own markup becomes its icon. */
export function hydrate(root = document) {
  for (const holder of root.querySelectorAll('[data-icon]')) {
    const name = holder.getAttribute('data-icon');
    holder.replaceChildren(name === 'logo' ? logo() : icon(name));
    holder.removeAttribute('data-icon');
  }
}

/* What a model's answer is made of: paragraphs, headings, lists, code, tables, and a link only where it is an http or https address. */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { MAX_LINE, MAX_TEXT, SHORTENED, blocks, inline } from '../../static/js/richtext.js';

test('a plain answer is a paragraph, and a line break inside it stays', () => {
  assert.deepEqual(blocks('Your balance is EUR 4,820.55.'), [{ type: 'p', text: 'Your balance is EUR 4,820.55.' }]);
  assert.deepEqual(blocks('One\nTwo\n\nThree'), [{ type: 'p', text: 'One\nTwo' }, { type: 'p', text: 'Three' }]);
  assert.deepEqual(blocks(''), []);
});

test('headings, bullets and numbered lists are blocks of their own', () => {
  const found = blocks('### Accounts\nYou have two:\n- ACC-1001\n* ACC-1002\n1. Check\n2) Pay');
  assert.deepEqual(found, [
    { type: 'heading', level: 3, text: 'Accounts' },
    { type: 'p', text: 'You have two:' },
    { type: 'ul', items: ['ACC-1001', 'ACC-1002'] },
    { type: 'ol', items: ['Check', 'Pay'] },
  ]);
  assert.equal(blocks('# Big')[0].level, 1);
  assert.equal(blocks('###### Small')[0].level, 3, 'the page has three sizes of heading');
});

test('a fenced block is code, whatever it holds, and one that is never closed runs to the end', () => {
  assert.deepEqual(blocks('Here:\n```json\n{"a": 1}\n- not a list\n```\nDone'), [
    { type: 'p', text: 'Here:' }, { type: 'code', lang: 'json', text: '{"a": 1}\n- not a list' }, { type: 'p', text: 'Done' }]);
  assert.deepEqual(blocks('```\nopen'), [{ type: 'code', lang: '', text: 'open' }]);
});

test('a table needs its divider line, and its rows end at the first line that is not one', () => {
  const found = blocks('| Account | Balance |\n|---|---:|\n| ACC-1001 | 4,820.55 |\n| ACC-1002 | 12.00 |\nTotal follows');
  assert.deepEqual(found, [
    { type: 'table', head: ['Account', 'Balance'], rows: [['ACC-1001', '4,820.55'], ['ACC-1002', '12.00']] },
    { type: 'p', text: 'Total follows' }]);
  assert.deepEqual(blocks('a | b\nno divider'), [{ type: 'p', text: 'a | b\nno divider' }]);
  assert.equal(blocks('Intro\n| a | b |\n|---|---|\n| 1 | 2 |')[1].type, 'table');
});

test('inside a line, bold and code are pieces, and a link only where its address is http or https', () => {
  assert.deepEqual(inline('Use **bold** and `code` here'), [
    { type: 'text', text: 'Use ' }, { type: 'strong', text: 'bold' }, { type: 'text', text: ' and ' }, { type: 'code', text: 'code' }, { type: 'text', text: ' here' }]);
  assert.deepEqual(inline('See [Gamma](https://gamma.example/x)'), [{ type: 'text', text: 'See ' }, { type: 'link', text: 'Gamma', href: 'https://gamma.example/x' }]);
  for (const bad of ['[x](javascript:alert(1))', '[x](data:text/html,hi)', '[x](//evil.example)', '[x](/api/trace)', '[x]( https://a.example)']) {
    assert.ok(inline(bad).every((piece) => piece.type !== 'link'), bad);
  }
});

test('nothing in an answer is ever read as markup: a tag is text', () => {
  const [paragraph] = blocks('<img src=x onerror=alert(1)> and <b>bold</b>');
  assert.equal(paragraph.type, 'p');
  assert.deepEqual(inline(paragraph.text), [{ type: 'text', text: '<img src=x onerror=alert(1)> and <b>bold</b>' }]);
});

/* ---- what an answer can cost the page: the thread that builds it is the one that draws the screen ------------------------------------- */

const quick = (fn, ms = 250) => {
  const started = performance.now();
  const out = fn();
  const took = performance.now() - started;
  assert.ok(took < ms, `took ${took.toFixed(0)} ms`);
  return out;
};

test('a heading line that is a long run of spaces ends in milliseconds, and keeps its words', () => {
  const found = quick(() => blocks(`## Title${' '.repeat(100000)}x`));
  assert.equal(found.length, 1);
  assert.equal(found[0].type, 'p', 'a line that long is text, not a heading');
  const heading = quick(() => blocks(`## Title${' '.repeat(1500)}x`));
  assert.deepEqual(heading.map((b) => b.type), ['heading']);
  assert.equal(heading[0].text.startsWith('Title'), true);
  quick(() => blocks(`# a${' '.repeat(20000)}b`));
  quick(() => blocks(`${' '.repeat(100000)}#`));
  quick(() => blocks(`${' '.repeat(100000)}-`));
  quick(() => blocks(`|${' '.repeat(100000)}\n|--|`));
});

test('a line of brackets, backticks or stars is plain text past the cap and fast below it', () => {
  quick(() => inline('[a'.repeat(100000)));
  quick(() => inline('`'.repeat(100000)));
  quick(() => inline('**a'.repeat(50000)));
  quick(() => inline('[a'.repeat(900)));
  assert.deepEqual(inline('x'.repeat(5000)), [{ type: 'text', text: 'x'.repeat(5000) }], 'a line past the cap is one piece of text');
  assert.deepEqual(inline(''), []);
});

test('an answer is read up to its cap and no further, and a tiny pattern cannot make a long line a heading', () => {
  const huge = 'word '.repeat(100000);
  const found = quick(() => blocks(huge));
  assert.equal(found.length, 1);
  assert.ok(found[0].text.length <= MAX_TEXT + 20, 'only the first characters are kept');
  assert.ok(found[0].text.endsWith('... (shortened)'), 'and the answer says so: the rest is not shown');
  assert.equal(SHORTENED, '(shortened)');
  assert.equal(blocks('a'.repeat(MAX_TEXT))[0].text.endsWith(SHORTENED), false, 'an answer that fits is not shortened');
  assert.equal(blocks('a'.repeat(MAX_TEXT + 1))[0].text.endsWith(SHORTENED), true);
  assert.deepEqual(blocks(`## ${'a'.repeat(MAX_LINE + 10)}`).map((b) => b.type), ['p']);
  assert.deepEqual(blocks(`- ${'a'.repeat(MAX_LINE + 10)}`).map((b) => b.type), ['p']);
});

test('the closing hashes of a heading go, and a hash that belongs to a word stays', () => {
  assert.equal(blocks('## Title ##')[0].text, 'Title');
  assert.equal(blocks('## Title   ')[0].text, 'Title');
  assert.equal(blocks('# C#')[0].text, 'C#');
  assert.equal(blocks('### Plans #1')[0].text, 'Plans #1');
});

test('the cap is the cap of a line: a paragraph of short lines keeps its bold, code and links however many it has', () => {
  const line = `**bold** and \`code\` and [Gamma](https://gamma.example/x) ${'word '.repeat(100)}`;      // about 560 characters
  const paragraph = [line, line, line, line].join('\n');
  assert.ok(paragraph.length > MAX_LINE);
  const pieces = inline(blocks(paragraph)[0].text);
  assert.deepEqual([pieces.filter((p) => p.type === 'strong').length, pieces.filter((p) => p.type === 'code').length,
    pieces.filter((p) => p.type === 'link').length], [4, 4, 4]);
  const text = pieces.map((p) => p.text).join('');
  assert.equal(text.split('\n').length, 4, 'the line breaks stay');
});

test('a line past the cap is plain text and the lines around it keep their formatting', () => {
  const huge = `**not bold** ${'x'.repeat(MAX_LINE)}`;
  const pieces = inline(`**one**\n${huge}\n\`two\``);
  assert.deepEqual(pieces.map((p) => p.type), ['strong', 'text', 'code']);
  assert.equal(pieces[1].text, `\n${huge}\n`);
});

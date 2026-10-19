/* The Tokens drawer: the user's own token, then the user token and the token Ace got, decoded for display: each fact once (the token itself is
   what Copy token gives). */
import { $, h, api } from './dom.js';
import { failure } from './errors.js';
import { state } from './store.js';
import { say, toast } from './ui.js';

function tokenCard(title, claims, keys, absent) {
  if (!claims) return h('section', { class: 'token' }, h('h3', { text: title }), h('p', { class: 'card-note', text: absent }));
  const facts = keys.map(([label, value]) => (value === undefined ? null : [label, Array.isArray(value) ? value.join(', ') : String(value)]))
    .filter(Boolean);
  return h('section', { class: 'token' }, h('h3', { text: title }),
    h('dl', {}, facts.map(([label, value]) => [h('dt', { text: label }), h('dd', { text: value })])));
}

/* The token is fetched when the drawer opens, after the claims (either may renew it), and kept only in the field below:
   the field is emptied when the drawer closes. */
async function openTokens() {
  if (!state.persona) return;
  const response = await api('/api/tokens');
  if (!response.ok) { toast(failure(response).text, 'error'); return; }
  const raw = await api('/api/token', { method: 'POST' });
  const { user, delegated } = response.data;
  $('#tokens-value').value = raw.ok ? raw.data.access_token : '';
  $('#tokens-copy').disabled = !raw.ok;
  $('#tokens-copied').textContent = raw.ok ? '' : failure(raw).text;
  $('#tokens-body').replaceChildren(
    tokenCard('User token', user, [['Subject', user.sub], ['User', user.username], ['Name', user.name], ['Role', user.role],
      ['Customer', user.customer_id], ['Accounts', user.accounts]], 'Not available'),
    tokenCard('Delegated token', delegated, [['Subject', delegated && delegated.sub], ['Acting agent', delegated && delegated.act && delegated.act.sub],
      ['Role', delegated && delegated.role], ['Customer', delegated && delegated.customer_id], ['Accounts', delegated && delegated.accounts]],
    state.gateway ? 'None yet: ask Ace something' : 'None without the gateway'));
  $('#tokens').showModal();
}

/* The write is made inside the click, before anything is awaited: a browser refuses it otherwise. Where it refuses anyway
   (an embedded browser, a page that is not secure) the token stays selected, ready for the keyboard. */
function copyToken() {
  const field = $('#tokens-value');
  const note = $('#tokens-copied');
  field.focus();
  field.select();
  const copied = () => { note.textContent = 'Copied'; say('Token copied'); };
  const selected = () => { note.textContent = 'Selected: press Ctrl+C or Cmd+C'; };
  const bySelection = () => {
    let done = false;
    try { done = document.execCommand('copy'); } catch { /* the selection is all there is */ }
    (done ? copied : selected)();
  };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(field.value).then(copied, bySelection);
  else bySelection();
}

export function initTokens() {
  $('#open-tokens').addEventListener('click', openTokens);
  $('#tokens-close').addEventListener('click', () => $('#tokens').close());
  $('#tokens-copy').addEventListener('click', copyToken);
  $('#tokens-value').addEventListener('click', (event) => event.target.select());
  $('#tokens').addEventListener('close', () => { $('#tokens-value').value = ''; });
  $('#tokens').addEventListener('click', (event) => { if (event.target === $('#tokens')) $('#tokens').close(); });
}

/* "Start the bank over": the balances and the cards go back to where the story starts. A plain command: it asks nothing, and says what it did. */
import { api, bus } from './dom.js';
import { failure } from './errors.js';
import { begin } from './store.js';
import { toast } from './ui.js';

let running = false;

export async function startOver() {
  if (running) return null;
  running = true;
  const done = begin();
  const response = await api('/api/presenter/reset', { method: 'POST', timeout: 30000 });
  running = false;
  done();
  if (!response.ok) {
    toast(`${failure(response).text} The bank is as it was.`, 'error');
    return null;
  }
  const { bank, traffic } = response.data;
  if (bank.ok) toast(traffic.ok ? 'The bank starts over: balances and cards are back.' : 'Balances and cards are back. The traffic counters did not answer.', traffic.ok ? 'ok' : 'info');
  else toast(`The bank did not reset (${bank.detail}). Presenter > Check says what is not ready.`, 'error');
  bus.emit('bank-reset', response.data);
  return response.data;
}

/* What the guide can ask of the page. Inside the Lab UI a guide may hold a button that does what a command of the rail does: the Lab UI posts
   {type: "gravitee-lab:action", id} to this page, and the page runs the command of that id exactly as its own button would: the person it is for, the
   answer in the conversation (in Teams for the budget), selected for Behind the answer. It answers nothing, and it does not know which page of the guide is read.
   It listens to its own parent only, to one of the Lab UI's origins only, and for a command of its list only; an id it does not know gets a notice.
   When the listener is installed the page says so ({type: "gravitee-lab:ready"}): an action asked before is the Lab UI's to keep until then.
   Standalone nothing listens and nothing is said. The ids are those of `commands.py`; the README lists them. */
import { LAB_ORIGINS, embedded, tell } from './embed.js';
import { state } from './store.js';
import { runCommand } from './commands.js';
import { closeSheet } from './inspector.js';
import { toast } from './ui.js';

const ID = /^[a-z0-9][a-z0-9-]{0,63}$/;        // what the Lab UI draws as a button: `action:<id>` with 1 to 64 of these

/* The id a message from the Lab UI asks for, or null for everything the page does not act on: a message from another window or another origin, one that is
   not an action, an id that is not an id. */
export function actionOf(event) {
  if (event.source !== window.parent || !LAB_ORIGINS.includes(event.origin)) return null;
  const message = event.data;
  if (!message || message.type !== 'gravitee-lab:action' || typeof message.id !== 'string' || !ID.test(message.id)) return null;
  return message.id;
}

/* What an action uses: the command of an id, how it runs, the sheet of Behind the answer, and the notice. A test hands in its own. */
const PORTS = { groups: () => state.groups, run: runCommand, close: () => closeSheet({ back: false }), toast };

/* Runs the command as its button does, or says there is none: the notice names the id, which is the guide author's to fix. Where Behind the answer is a sheet
   it covers the page and holds the answer it was opened on: it is closed first, so that the answer of the command is the one in front of the person (the
   focus is not taken from the guide, which the person is in). A click on a command's own button cannot find it open: the sheet makes the rest inert. */
export function act(id, ports = PORTS) {
  const groups = ports.groups();
  const command = groups.flatMap((group) => group.commands).find((one) => one.id === id);
  if (command) {
    ports.close();
    ports.run(command);
  } else {
    ports.toast(groups.length ? `The app has no command "${id}".` : 'The commands are not available.', 'info');
  }
}

export function initActions(ports = PORTS) {
  if (!embedded()) return;
  window.addEventListener('message', (event) => {
    const id = actionOf(event);
    if (id) act(id, ports);
  });
  tell({ type: 'gravitee-lab:ready' });
}

/* The page of ACME Bank. No framework, no build step: plain DOM modules, and only textContent for anything that came from a
   server, so nothing a model or a gateway says can become markup. */
import { api } from './js/dom.js';
import { hydrate } from './js/icons.js';
import { state } from './js/store.js';
import { initHeader } from './js/header.js';
import { initAsking } from './js/asking.js';
import { initEmbed } from './js/embed.js';
import { initActions } from './js/actions.js';
import { initChat } from './js/chat.js';
import { initComposer } from './js/composer.js';
import { initInspector } from './js/inspector.js';
import { initMonitor } from './js/monitor.js';
import { initMoney } from './js/money.js';
import { initTokens } from './js/tokens.js';
import { initCommands, loadCommands, renderCommands } from './js/commands.js';
import { initTeams } from './js/teams.js';
import { initDevelopers } from './js/developers.js';
import { initPresenter } from './js/presenter.js';
import { initRouter } from './js/router.js';
import { adopt } from './js/session.js';

async function start() {
  initEmbed();           // a way into Gamma is handed to the Lab UI when the page is framed: the page listens before it awaits anything
  hydrate();
  const [config, personas, session] = await Promise.all([api('/api/config'), api('/api/personas'), api('/api/session'), loadCommands()]);
  if (config.ok) state.config = config.data;
  state.personas = personas.ok ? personas.data : [];

  initHeader();
  initAsking();
  initChat();
  initComposer();
  initMoney();
  initInspector();
  initMonitor();
  initTokens();
  initCommands();
  initTeams();
  initDevelopers();
  initPresenter();
  initRouter();
  adopt(session.ok ? session.data : null);
  renderCommands();
  initActions();         // the page runs the commands, so the guide may ask for them (inside the Lab UI): it says so when it can
}

start();

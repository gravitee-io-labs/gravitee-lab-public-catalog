"use strict";

const LAB_UIS = ["http://localhost:9000", "http://127.0.0.1:9000"];   // where the Lab UI is served from
const PORTAL = "http://localhost:8085/next/";
const $ = (id) => document.getElementById(id);

const HOSTS = [["orders", "orders"], ["payments", "payments"], ["partners", "partners"]];
const CERT_IDENTITIES = [["fulfillment", "Fulfillment"], ["billing", "Billing"], ["stranger", "Stranger"], ["anonymous", "None"]];
const PARTNER_IDENTITIES = [["partner", "SSO token"], ["anonymous", "None"]];
const identitiesOf = (host) => (host === "partners" ? PARTNER_IDENTITIES : CERT_IDENTITIES);
const FQDN = { orders: "orders.kafka.local", payments: "payments.kafka.local", partners: "partners.kafka.local" };

const state = {
  config: null,
  producer: { channel: "kafka", host: "orders", identity: "fulfillment", acks: "all" },
  consumer: { channel: "kafka", host: "orders", identity: "fulfillment", who: "dashboard", api: "orders", source: null, count: 0, lastError: "" },
  switches: {},
  busy: new Set(),
  working: "",      // what the busy switches are doing, said next to them
  sni: "orders",
  links: null,
};

function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== false && value != null) node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) if (child != null && child !== false) node.append(child);
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, options.body === undefined ? options : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(options.body) });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

const clock = (t) => new Date(t || Date.now()).toLocaleTimeString([], { hour12: false });
const bytes = (n) => (n >= 1024 ? `${(n / 1024).toFixed(n >= 10240 ? 0 : 1)} KB` : `${n} B`);
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// --- Segmented controls -------------------------------------------------------------------------------------------------

function seg(id, options, value, onChange, small = false) {
  const root = $(id);
  root.replaceChildren(...options.map(([v, label]) => h("button", { "data-v": v, role: root.getAttribute("role") === "tablist" ? "tab" : null,
    "aria-selected": String(v === value), onclick: () => onChange(v) }, label)));
  if (small) root.classList.add("small");
}

// --- Services and switches ----------------------------------------------------------------------------------------------

async function refreshStatus() {
  try {
    const status = await api("/api/status");
    const names = { gateway: "Gateway", broker: "Broker", azurite: "Azurite", management: "Management API" };
    $("pills").replaceChildren(...Object.entries(names).map(([key, label]) => h("span", { class: `pill ${status[key] ? "up" : "down"}` }, label)));
  } catch {
    $("pills").replaceChildren(h("span", { class: "pill down" }, "App"));
  }
}

const DEPLOYING = "Deploying to the gateway…";

function renderSwitches() {
  const groups = new Map();
  for (const item of state.config.switches) {
    if (!groups.has(item.group)) groups.set(item.group, []);
    groups.get(item.group).push(item);
  }
  const nodes = [];
  for (const [name, items] of groups) {
    nodes.push(h("div", { class: "group" }, h("b", {}, name), items.map((item) => {
      const on = state.switches[item.id];
      return h("button", { class: "toggle", role: "switch", id: `switch-${item.id}`, "aria-checked": String(on === true), "aria-busy": String(state.busy.has(item.id)),
        title: item.hint, disabled: on === null || on === undefined || state.busy.size > 0 ? true : false, onclick: () => flip(item.id) },
        h("span", { class: state.busy.has(item.id) && state.working === DEPLOYING ? "knob busy" : "knob" }), item.label);
    })));
  }
  nodes.push(h("span", { class: "spacer" }),
    state.busy.size ? h("span", { class: "working", role: "status" }, h("span", { class: "ring" }), state.working) : null,
    h("button", { class: "btn", id: "reset", onclick: reset, disabled: state.busy.size > 0 }, "Reset"));
  $("switches").replaceChildren(...nodes.filter(Boolean));
}

async function refreshSwitches() {
  if (state.busy.size) return;
  try { state.switches = (await api("/api/switches")).states; } catch { state.switches = Object.fromEntries(state.config.switches.map((s) => [s.id, null])); }
  renderSwitches();
}

async function setSwitches(wanted) {
  const ids = Object.keys(wanted);
  state.working = DEPLOYING;
  ids.forEach((id) => state.busy.add(id));
  renderSwitches();
  try {
    const answer = await api("/api/switches", { body: { wanted } });
    state.switches = answer.states;
    if (answer.cleared) { clearBrokerView(); note(`Topic cleared first: ${answer.cleared} records, written in clear, cannot be decrypted`); }
  } catch (error) {
    note(error.message, true);
  } finally {
    state.busy.clear();
    renderSwitches();
    loadBlobs();
  }
}

function flip(id) { return setSwitches({ [id]: !state.switches[id] }); }

async function reset() {
  state.working = "Resetting…";
  state.config.switches.forEach((s) => state.busy.add(s.id));
  renderSwitches();
  try {
    const answer = await api("/api/reset", { body: {} });
    state.switches = answer.states;
    clearBrokerView();
    clearConsumer();
  } catch (error) {
    note(error.message, true);
  } finally {
    state.busy.clear();
    renderSwitches();
  }
}

function note(message, bad = false) {
  addMessage(h("li", { class: bad ? "error" : "status" }, message));
}

// --- Producer -----------------------------------------------------------------------------------------------------------

function commandText() {
  const p = state.producer;
  if (p.channel === "http") {
    return `curl -X POST "$GATEWAY/orders/" \\\n  -H "X-Gravitee-Api-Key: $ORDERS_KEY" -H "Content-Type: application/json" \\\n  -d '{"orderId":"ORD-1001","customer":"Léa Martin","amount":${$("amount").value},"country":"${$("country").value}",...}'`;
  }
  if (p.channel === "avro") {
    return `# a legacy producer: Avro with the schema id of the registry, straight to the broker\nkcat -P -b kafka:9091 -t acme.orders.avro.v1 ...`;
  }
  const tls = ["-X security.protocol=ssl", "-X ssl.ca.location=/kafka-certs/kafka-gateway.crt"];
  if (p.identity === "partner") {
    tls.splice(0, 1, "-X security.protocol=sasl_ssl", "-X sasl.mechanisms=OAUTHBEARER", "-X sasl.oauthbearer.method=oidc",
      "-X sasl.oauthbearer.client.id=partner-portal", "-X sasl.oauthbearer.client.secret=$PARTNER_SECRET", "-X sasl.oauthbearer.token.endpoint.url=$TOKEN_URL");
    tls.splice(1, 0, "-X ssl.ca.location=/kafka-certs/kafka-gateway.crt");
    tls.pop();
  } else if (p.identity !== "anonymous") {
    tls.push(`-X ssl.certificate.location=/certs/${p.identity}.crt`, `-X ssl.key.location=/certs/${p.identity}.key`);
  }
  const extra = [p.acks === "all" ? "" : `-X acks=${p.acks === "none" ? 0 : 1}`, $("trace").checked ? "-H x-trace=1" : ""].filter(Boolean);
  const topic = p.host === "payments" ? "payments" : "orders";
  return `echo '{"orderId":"ORD-1001",...}' | kcat -P -b ${FQDN[p.host]}:9092 -t ${topic} \\\n  ${[...tls, ...extra].join(" \\\n  ")}`;
}

function showCommand() { $("command-text").textContent = commandText(); }

function renderProducer() {
  const p = state.producer;
  if (!identitiesOf(p.host).some(([v]) => v === p.identity)) p.identity = p.host === "partners" ? "partner" : "fulfillment";
  seg("producer-channel", [["kafka", "Kafka"], ["http", "HTTP POST"], ["avro", "Avro"]], p.channel, (v) => { p.channel = v; renderProducer(); });
  seg("producer-host", HOSTS, p.host, (v) => { p.host = v; renderProducer(); }, true);
  seg("producer-identity", identitiesOf(p.host), p.identity, (v) => { p.identity = v; renderProducer(); }, true);
  seg("producer-acks", [["all", "All"], ["leader", "Leader"], ["none", "None"]], p.acks, (v) => { p.acks = v; renderProducer(); }, true);
  const kafka = p.channel === "kafka";
  $("producer-kafka-opts").hidden = !kafka;
  $("producer-rules-opts").hidden = !kafka;
  $("topic-admin").hidden = !kafka;
  $("send-flood").hidden = !kafka;
  $("send-large").hidden = p.channel === "avro";
  showCommand();
}

function routeFor(result) {
  const p = state.producer;
  const via = p.channel === "http" ? "POST /orders/" : p.channel === "avro" ? "no gateway" : `${FQDN[p.host]}:9092`;
  const who = { fulfillment: "fulfillment", billing: "billing", stranger: "stranger", anonymous: "no credential", partner: "SSO token" }[p.identity];
  $("route-producer").textContent = p.channel === "http" ? "HTTP POST · API key" : p.channel === "avro" ? "Avro producer" : `Kafka · ${who}`;
  $("route-gateway").textContent = via;
  $("route-broker").textContent = p.channel === "avro" ? state.config.topics.avro : p.host === "payments" ? state.config.topics.payments : state.config.topics.orders;
  const c = state.consumer;
  $("route-consumer").textContent = { kafka: `Kafka · ${c.host}`, get: "HTTP GET", sse: "SSE", webhook: "Webhook" }[c.channel];
  pulse(result.ok, p.channel === "avro");
}

function pulse(ok, direct) {
  const stops = ["stop-producer", "stop-gateway", "stop-broker"].map($);
  const links = ["link-in", "link-mid"].map($);
  [...stops, ...links].forEach((n) => n.classList.remove("lit", "run", "refused"));
  void $("route").offsetWidth;
  stops[0].classList.add("lit");
  links[0].classList.add("run");
  if (direct) { setTimeout(() => stops[2].classList.add("lit"), 450); return; }
  if (!ok) { links[0].classList.add("refused"); stops[1].classList.add("refused"); return; }
  setTimeout(() => { stops[1].classList.add("lit"); links[1].classList.add("run"); }, 450);
  setTimeout(() => stops[2].classList.add("lit"), 900);
}

function outcomeChip(result) {
  if (!result.ok) return h("span", { class: "chip bad" }, result.status ? String(result.status) : "Refused");
  if (result.unacknowledged) return h("span", { class: "chip warn" }, "No ack");
  if (result.channel === "http") return h("span", { class: "chip ok" }, `${result.status} · ${result.ms} ms`);
  if (result.channel === "avro") return h("span", { class: "chip ok" }, `schema ${result.schema} · @${result.offset}`);
  const count = result.delivered > 1 ? `${result.delivered} records · ` : "";
  return h("span", { class: "chip ok" }, `${count}p${result.partition} @${result.offset} · ${result.ms} ms`);
}

function logRow(row, result, label) {
  const parts = [h("time", {}, clock()), h("span", {}, label || result.order || ""), outcomeChip(result)];
  row.replaceChildren(...parts);
  if (result.throttle_ms >= 500) row.append(h("span", { class: "why warn" }, `The gateway asked the client to slow down: ${(result.throttle_ms / 1000).toFixed(1)} s`));
  if (!result.ok) row.append(h("span", { class: "why" }, result.error));
  if (result.unacknowledged) row.append(h("span", { class: "why warn" }, "acks=0: the client never hears whether the gateway accepted it. Check the Broker column"));
}

async function send(extra = {}) {
  const p = state.producer;
  const amount = Number($("amount").value);
  const body = { channel: p.channel, host: p.host, identity: p.identity, acks: p.acks, trace: $("trace").checked, country: $("country").value,
    customer: $("customer").value || undefined, amount: Number.isFinite(amount) && amount > 0 ? amount : undefined, ...extra };
  const tag = p.channel === "http" ? "HTTP" : p.channel === "avro" ? "Avro" : `${p.host} · ${p.identity}`;
  const row = h("li", {}, h("time", {}, clock()), h("span", {}, "Sending…"), h("span", { class: "chip" }, tag));
  $("producer-log").prepend(row);
  try {
    const result = await api("/api/produce", { body });
    routeFor(result);
    logRow(row, result);
  } catch (error) {
    row.replaceChildren(h("time", {}, clock()), h("span", {}, ""), h("span", { class: "chip bad" }, "Error"), h("span", { class: "why" }, error.message));
  }
  while ($("producer-log").children.length > 30) $("producer-log").lastChild.remove();
}

async function createTopic(name, partitions) {
  const p = state.producer;
  $("topic-name").value = name;
  $("topic-partitions").value = partitions;
  const row = h("li", {}, h("time", {}, clock()), h("span", {}, `Create ${name}`), h("span", { class: "chip" }, `${partitions} partition${partitions > 1 ? "s" : ""}`));
  $("producer-log").prepend(row);
  try {
    const result = await api("/api/topic", { body: { host: p.host, identity: p.identity, name, partitions } });
    row.replaceChildren(h("time", {}, clock()), h("span", {}, `Create ${name}`),
      h("span", { class: `chip ${result.ok ? "ok" : "bad"}` }, result.ok ? "Created" : "Refused"));
    if (!result.ok) row.append(h("span", { class: "why" }, result.error));
  } catch (error) {
    row.replaceChildren(h("time", {}, clock()), h("span", {}, `Create ${name}`), h("span", { class: "chip bad" }, "Error"), h("span", { class: "why" }, error.message));
  }
}

// --- Consumer -----------------------------------------------------------------------------------------------------------

function renderConsumer() {
  const c = state.consumer;
  if (!identitiesOf(c.host).some(([v]) => v === c.identity)) c.identity = c.host === "partners" ? "partner" : "fulfillment";
  if (c.api === "avro" && c.who !== "dashboard") c.who = "dashboard";
  seg("consumer-channel", [["kafka", "Kafka"], ["get", "GET"], ["sse", "SSE"], ["webhook", "Webhook"]], c.channel, (v) => { c.channel = v; renderConsumer(); if (c.source) connect(); });
  seg("consumer-host", HOSTS, c.host, (v) => { c.host = v; renderConsumer(); if (c.source) connect(); }, true);
  seg("consumer-identity", identitiesOf(c.host), c.identity, (v) => { c.identity = v; renderConsumer(); if (c.source) connect(); }, true);
  seg("consumer-who", [["dashboard", "Dashboard"], ["france", "France"], ["germany", "Germany"]], c.who, (v) => { c.who = v; if (v !== "dashboard") c.api = "orders"; renderConsumer(); if (c.source) connect(); }, true);
  seg("consumer-api", [["orders", "Orders"], ["avro", "Avro"]], c.api, (v) => { c.api = v; renderConsumer(); if (c.source) connect(); }, true);
  $("consumer-kafka-opts").hidden = c.channel !== "kafka";
  $("consumer-http-opts").hidden = !["get", "sse"].includes(c.channel);
  $("consumer-hook-opts").hidden = c.channel !== "webhook";
}

function addMessage(node) {
  const list = $("consumer-messages");
  list.prepend(node);
  while (list.children.length > 60) list.lastChild.remove();
  $("consumer-empty").hidden = list.children.length > 0;
}

function clearConsumer() {
  $("consumer-messages").replaceChildren();
  state.consumer.count = 0;
  $("consumer-count").textContent = "0";
  $("consumer-empty").hidden = false;
}

function setConsumerState(text, kind = "") {
  const node = $("consumer-state");
  node.textContent = text;
  node.className = `state ${kind}`;
}

function disconnect() {
  const c = state.consumer;
  if (c.source) c.source.close();
  c.source = null;
  $("consume").textContent = "Connect";
  setConsumerState("Idle");
}

function connect() {
  disconnect();
  clearConsumer();
  const c = state.consumer;
  c.lastError = "";
  const query = new URLSearchParams();
  if (c.channel === "kafka") {
    query.set("host", c.host);
    query.set("identity", c.identity);
    if ($("from-beginning").checked) query.set("from", "beginning");
  } else if (c.channel === "get" || c.channel === "sse") {
    query.set("who", c.who);
    query.set("api", c.api);
  }
  const source = new EventSource(`/api/stream/${c.channel}?${query}`);
  c.source = source;
  $("consume").textContent = "Disconnect";
  setConsumerState("Connecting…");
  source.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "status") { setConsumerState(data.ready ? "Listening" : "Connecting…", data.ready ? "live" : ""); addMessage(h("li", { class: "status" }, data.message)); }
    else if (data.type === "error") {
      setConsumerState(data.transient ? "Reconnecting…" : "Refused", data.transient ? "" : "fail");
      if (data.message !== c.lastError) addMessage(h("li", { class: "error" }, data.message));
      c.lastError = data.message;
    } else if (data.type === "message") {
      setConsumerState("Receiving", "live");
      c.lastError = "";
      c.count += 1;
      $("consumer-count").textContent = String(c.count);
      addMessage(messageRow(data, true));
    }
  };
  source.onerror = () => { source.close(); if (c.source === source) { c.source = null; $("consume").textContent = "Connect"; setConsumerState("Disconnected", "fail"); } };
}

// --- Rendering of a record ----------------------------------------------------------------------------------------------

const CIPHER = /^[A-Za-z0-9+/]{32,}={0,2}$/;

function renderValue(text) {
  let parsed;
  try { parsed = JSON.parse(text); } catch { return h("div", { class: "value" }, text); }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return h("div", { class: "value" }, text);
  const parts = [h("span", {}, "{")];
  Object.entries(parsed).forEach(([key, value], index) => {
    const long = typeof value === "string" && value.length > 90;
    const shown = long ? `${value.slice(0, 24)}… ${bytes(value.length)}` : value;
    const cipher = typeof value === "string" && CIPHER.test(value) && !long;
    const cls = cipher ? "c" : typeof value === "number" ? "n" : "s";
    parts.push(h("span", {}, index ? ", " : " "), h("span", { class: "k" }, `"${key}"`), h("span", {}, ": "),
      h("span", { class: cls }, typeof value === "string" ? `"${shown}"` : JSON.stringify(shown)));
  });
  parts.push(h("span", {}, " }"));
  return h("div", { class: "value" }, parts);
}

function messageRow(data, withChannel) {
  const meta = [h("time", {}, clock(data.received ? data.received * 1000 : undefined))];
  if (withChannel) meta.push(h("span", { class: "chip" }, data.channel || "kafka"));
  if (data.topic) meta.push(h("span", { class: "chip" }, data.topic));
  if (data.size != null) meta.push(h("span", {}, bytes(data.size)));
  for (const [name, value] of data.headers || []) meta.push(h("span", { class: "chip" }, `${name}: ${value}`.slice(0, 60)));
  return h("li", {}, h("div", { class: "meta" }, meta), renderValue(data.value));
}

function brokerRow(data) {
  const headers = data.headers || [];
  const encrypted = headers.some(([name]) => name.startsWith("X-Gravitee-Encryption-"));
  const pointer = headers.find(([name]) => name === "__GIO_OFFLOADING_POLICY");
  const meta = [h("time", {}, clock()), h("span", { class: "chip" }, data.topic), h("span", {}, `@${data.offset}`), h("span", {}, bytes(data.size))];
  if (encrypted) meta.push(h("span", { class: "chip cipher" }, "Encrypted"));
  if (pointer) meta.push(h("span", { class: "chip accent" }, "Offloaded"));
  if (data.binary) meta.push(h("span", { class: "chip accent" }, `Avro · schema ${data.schema}`));
  let body;
  if (pointer) {
    const name = data.value.split("/").pop();
    body = h("div", { class: "value pointer" }, data.value.replace(name, ""), h("a", { onclick: () => previewBlob(name) }, name));
  } else {
    body = data.binary ? h("div", { class: "value dim" }, data.value) : renderValue(data.value);
  }
  return h("li", {}, h("div", { class: "meta" }, meta), body);
}

function openBroker() {
  const source = new EventSource("/api/stream/broker");
  source.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type !== "message") return;
    const list = $("broker-records");
    list.prepend(brokerRow(data));
    while (list.children.length > 40) list.lastChild.remove();
    $("broker-empty").hidden = true;
    if (data.headers.some(([name]) => name === "__GIO_OFFLOADING_POLICY")) setTimeout(loadBlobs, 500);
  };
  source.onerror = () => { source.close(); setTimeout(openBroker, 3000); };
}

// --- SNI, Azurite and the Console ---------------------------------------------------------------------------------------

async function probe() {
  const result = $("sni-result");
  result.replaceChildren(h("dt", {}, "Host in the handshake"), h("dd", {}, "…"));
  try {
    const found = await api(`/api/probe?host=${state.sni}&identity=${state.sni === "partners" ? "partner" : "fulfillment"}`);
    const rows = [["Host in the handshake", [h("span", { class: "chip accent" }, found.sni)]]];
    if (found.tls && found.tls.ok) {
      rows.push(["TLS", [h("span", { class: "chip ok" }, `${found.tls.protocol} · ${found.tls.cipher}`)]]);
      rows.push(["Certificate", [h("span", { class: "chip" }, found.tls.subject), ...found.tls.san.map((name) => h("span", { class: "chip" }, name))]]);
      rows.push(["Kafka API", [h("span", { class: `chip ${found.kafka === "answered" ? "ok" : "bad"}` }, found.kafka === "answered" ? "Answered" : "Closed: no API has this host")]]);
    } else {
      rows.push(["TLS", [h("span", { class: "chip bad" }, found.tls ? found.tls.error : "No answer")]]);
    }
    if (found.topics) rows.push(["Topics seen", found.topics.length ? found.topics.map((name) => h("span", { class: "chip" }, name)) : [h("span", { class: "chip" }, "none")]]);
    if (found.brokers) rows.push(["Brokers returned", found.brokers.map((name) => h("span", { class: "chip" }, name))]);
    result.replaceChildren(...rows.flatMap(([term, nodes]) => [h("dt", {}, term), h("dd", {}, nodes)]));
  } catch (error) {
    result.replaceChildren(h("dt", {}, "Probe"), h("dd", {}, h("span", { class: "chip bad" }, error.message)));
  }
}

async function loadBlobs() {
  try {
    const { blobs } = await api("/api/blobs");
    $("blob-list").replaceChildren(...blobs.map((blob) => h("li", { onclick: () => previewBlob(blob.name) },
      h("span", { class: "name" }, blob.name), h("span", { class: "chip" }, bytes(blob.size)))));
    $("blob-empty").hidden = blobs.length > 0;
  } catch { $("blob-empty").hidden = false; }
}

async function previewBlob(name) {
  try {
    const found = await api(`/api/blob?name=${encodeURIComponent(name)}`);
    $("blob-preview").hidden = false;
    $("blob-preview").textContent = `${found.name} · ${bytes(found.size)}\n${found.head}…`;
    $("blob-preview").scrollIntoView({ block: "nearest" });
  } catch (error) { $("blob-preview").hidden = false; $("blob-preview").textContent = error.message; }
}

// The Console, the portal: a link asks the Lab UI to show the page in the tab of that UI, or opens it in a new tab outside the Lab UI
function openUrl(url) {
  if (parent !== window) for (const origin of LAB_UIS) parent.postMessage({ type: "gravitee-lab:open", url }, origin);
  else window.open(url, "_blank", "noopener");
}

function consoleUrl(kind) {
  const l = state.links;
  if (!l) return null;
  const api = (name, page) => (l.apis[name] ? `${l.console}/#!/default/apis/${l.apis[name]}/${page}` : null);
  return {
    "kafka-traffic": api("Orders Kafka", "v4/analytics?period=1h"),
    "kafka-logs": api("Orders Kafka", "v4/runtime-logs-native"),
    "kafka-policies": api("Orders Kafka", "v4/policy-studio/0/0"),
    "partners-plan": api("Partners Kafka", "plans"),
    "partners-policies": api("Partners Kafka", "v4/policy-studio/0/0"),
    "kafka-entrypoints": api("Orders Kafka", "v4/entrypoints"),
    "kafka-endpoints": api("Orders Kafka", "v4/endpoints"),
    "kafka-plans": api("Orders Kafka", "plans"),
    "events-entrypoints": api("Orders Events", "v4/entrypoints"),
    "events-endpoints": api("Orders Events", "v4/endpoints"),
    "events-policies": api("Orders Events", "v4/policy-studio/0/0"),
    "events-plans": api("Orders Events", "plans"),
    "avro-policies": api("Orders Avro", "v4/policy-studio/0/0"),
    explorer: l.cluster ? `${l.console}/#!/default/clusters/kafka-standalone/${l.cluster}/explorer/topics` : null,
    applications: `${l.console}/#!/default/applications`,
    portal: `${PORTAL}catalog`,
  }[kind];
}

const CONSOLE_LINKS = [["kafka-traffic", "Orders Kafka · API Traffic"], ["kafka-logs", "Orders Kafka · Connection logs"], ["kafka-policies", "Orders Kafka · Policies"],
  ["explorer", "Kafka Explorer"], ["events-plans", "Orders Events · Plans"], ["applications", "Applications"], ["portal", "Developer Portal · Catalog"]];

function renderConsoleLinks() {
  $("console-links").replaceChildren(...CONSOLE_LINKS.map(([kind, label]) => {
    const url = consoleUrl(kind);
    // The portal has no tab of the Lab UI: it opens in the browser, from this click, which a message to the Lab UI could not give
    return h("li", { onclick: () => url && (kind === "portal" ? window.open(url, "_blank", "noopener") : openUrl(url)), class: url ? "" : "off" }, h("span", { class: "name" }, label), h("span", { class: "chip" }, "Open"));
  }));
}

async function loadLinks() {
  try { state.links = await api("/api/links"); } catch { state.links = null; }
  renderConsoleLinks();
}

// --- Actions of the guide -----------------------------------------------------------------------------------------------

function asProducer(channel, host, identity) {
  const p = state.producer;
  Object.assign(p, { channel, host, identity });
  renderProducer();
}

function asConsumer(change) {
  Object.assign(state.consumer, change);
  if (state.consumer.channel === "kafka") $("from-beginning").checked = true;      // a guide's button reads what is there, and misses nothing sent right after it
  renderConsumer();
  connect();
}

function setOptions(acks, trace) {
  state.producer.acks = acks;
  $("trace").checked = trace;
  renderProducer();
}

const ACTIONS = {
  // Who writes
  "producer-http": () => asProducer("http", "orders", "fulfillment"),
  "producer-avro": () => asProducer("avro", "orders", "fulfillment"),
  "producer-kafka": () => asProducer("kafka", "orders", "fulfillment"),
  "producer-fulfillment": () => asProducer("kafka", "orders", "fulfillment"),
  "producer-billing": () => asProducer("kafka", "orders", "billing"),
  "producer-stranger": () => asProducer("kafka", "orders", "stranger"),
  "producer-anonymous": () => asProducer("kafka", "orders", "anonymous"),
  "producer-partner": () => asProducer("kafka", "partners", "partner"),
  "producer-payments": () => asProducer("kafka", "payments", "fulfillment"),
  // What is sent, and from whom
  "send-order": () => send(),
  "send-http": () => { asProducer("http", "orders", "fulfillment"); return send(); },
  "send-avro": () => { asProducer("avro", "orders", "fulfillment"); return send(); },
  "send-as-fulfillment": () => { asProducer("kafka", "orders", "fulfillment"); return send(); },
  "send-as-billing": () => { asProducer("kafka", "orders", "billing"); return send(); },
  "send-as-stranger": () => { asProducer("kafka", "orders", "stranger"); return send(); },
  "send-as-anonymous": () => { asProducer("kafka", "orders", "anonymous"); return send(); },
  "send-as-partner": () => { asProducer("kafka", "partners", "partner"); return send(); },
  "send-high-value": () => { $("amount").value = 1500; return send({ amount: 1500 }); },
  "send-low-value": () => { $("amount").value = 30; return send({ amount: 30 }); },
  "send-large": () => send({ large: true }),
  "send-burst": () => burst(),
  "send-flood": () => send({ count: 40 }),
  "send-france": () => { $("country").value = "FR"; $("amount").value = 1500; return send({ country: "FR", amount: 1500 }); },
  "send-germany": () => { $("country").value = "DE"; $("amount").value = 1500; return send({ country: "DE", amount: 1500 }); },
  "send-spain": () => { $("country").value = "ES"; $("amount").value = 1500; return send({ country: "ES", amount: 1500 }); },
  "send-unsafe": () => { setOptions("none", false); return send(); },
  "send-untraced": () => { setOptions("all", false); return send(); },
  "send-safe": () => { setOptions("all", true); return send(); },
  "topic-bad-name": () => createTopic("orders-Bad_Name", 1),
  "topic-too-big": () => createTopic("orders-big", 12),
  "topic-ok": () => createTopic("orders-eu", 3),
  // Who reads
  "consumer-kafka": () => asConsumer({ channel: "kafka", host: "orders", identity: "fulfillment" }),
  "consumer-fulfillment": () => asConsumer({ channel: "kafka", host: "orders", identity: "fulfillment" }),
  "consumer-billing": () => asConsumer({ channel: "kafka", host: "orders", identity: "billing" }),
  "consumer-stranger": () => asConsumer({ channel: "kafka", host: "orders", identity: "stranger" }),
  "consumer-anonymous": () => asConsumer({ channel: "kafka", host: "orders", identity: "anonymous" }),
  "consumer-partner": () => asConsumer({ channel: "kafka", host: "partners", identity: "partner" }),
  "consumer-get": () => asConsumer({ channel: "get", who: "dashboard", api: "orders" }),
  "consumer-sse": () => asConsumer({ channel: "sse", who: "dashboard", api: "orders" }),
  "consumer-webhook": () => asConsumer({ channel: "webhook" }),
  "consumer-france": () => asConsumer({ channel: "sse", who: "france", api: "orders" }),
  "consumer-germany": () => asConsumer({ channel: "sse", who: "germany", api: "orders" }),
  "consumer-dashboard": () => asConsumer({ channel: "sse", who: "dashboard", api: "orders" }),
  "consumer-avro": () => asConsumer({ channel: "get", who: "dashboard", api: "avro" }),
  // The policies
  "shape-on": () => setSwitches({ "http-filter": true, "http-reshape": true }),
  "avro-on": () => setSwitches({ "avro-json": true }),
  "kafka-filter-on": () => setSwitches({ "kafka-filter": true }),
  "encrypt-on": () => setSwitches({ "kafka-encrypt": true }),
  "offload-on": () => setSwitches({ "kafka-offload": true }),
  "guardrails-on": () => setSwitches({ guardrails: true }),
  "safe-producers-on": () => setSwitches({ "safe-producers": true }),
  "quota-on": () => setSwitches({ quota: true }),
  "reset": () => reset(),
  "clear-topics": () => clearTopics(),
  // Looks
  "probe-orders": () => { state.sni = "orders"; renderSni(); return probe(); },
  "probe-payments": () => { state.sni = "payments"; renderSni(); return probe(); },
  "probe-partners": () => { state.sni = "partners"; renderSni(); return probe(); },
  "probe-ghost": () => { state.sni = "ghost"; renderSni(); return probe(); },
  // The Console and the portal
  "open-kafka-traffic": () => openConsole("kafka-traffic"),
  "open-kafka-logs": () => openConsole("kafka-logs"),
  "open-kafka-policies": () => openConsole("kafka-policies"),
  "open-partners-plan": () => openConsole("partners-plan"),
  "open-partners-policies": () => openConsole("partners-policies"),
  "open-kafka-entrypoints": () => openConsole("kafka-entrypoints"),
  "open-kafka-endpoints": () => openConsole("kafka-endpoints"),
  "open-kafka-plans": () => openConsole("kafka-plans"),
  "open-events-entrypoints": () => openConsole("events-entrypoints"),
  "open-events-endpoints": () => openConsole("events-endpoints"),
  "open-events-policies": () => openConsole("events-policies"),
  "open-events-plans": () => openConsole("events-plans"),
  "open-avro-policies": () => openConsole("avro-policies"),
  "open-explorer": () => openConsole("explorer"),
  "open-applications": () => openConsole("applications"),
};

async function openConsole(kind) {
  if (!consoleUrl(kind)) await loadLinks();
  const url = consoleUrl(kind);
  if (url) openUrl(url);
  else note("The Console has no such page yet: the seed has not finished", true);
}

async function burst() {
  for (let i = 0; i < 5; i += 1) { await send(); await wait(250); }
}

function clearBrokerView() {
  $("broker-records").replaceChildren();
  $("broker-empty").hidden = false;
}

async function clearTopics() {
  try { const { cleared } = await api("/api/clear", { body: {} }); clearBrokerView(); note(`${cleared} records removed`); }
  catch (error) { note(error.message, true); }
}

function renderSni() {
  seg("sni-host", [["orders", "orders"], ["payments", "payments"], ["partners", "partners"], ["ghost", "ghost"]], state.sni, (v) => { state.sni = v; renderSni(); }, true);
}

addEventListener("message", (event) => {
  if (event.source === parent && LAB_UIS.includes(event.origin) && event.data && event.data.type === "gravitee-lab:action") {
    const run = ACTIONS[event.data.id];
    if (run) run();
  }
});

// --- Start --------------------------------------------------------------------------------------------------------------

async function start() {
  state.config = await api("/api/config");
  $("hook-url").textContent = state.config.hook;
  renderProducer();
  renderConsumer();
  renderSni();
  $("send").addEventListener("click", () => send());
  $("send-burst").addEventListener("click", burst);
  $("send-flood").addEventListener("click", () => send({ count: 40 }));
  $("send-large").addEventListener("click", () => send({ large: true }));
  $("topic-create").addEventListener("click", () => createTopic($("topic-name").value.trim(), Number($("topic-partitions").value) || 1));
  $("consume").addEventListener("click", () => (state.consumer.source ? disconnect() : connect()));
  $("consumer-clear").addEventListener("click", clearConsumer);
  $("broker-clear").addEventListener("click", clearTopics);
  $("sni-probe").addEventListener("click", probe);
  $("blobs-refresh").addEventListener("click", loadBlobs);
  $("hook-copy").addEventListener("click", () => navigator.clipboard && navigator.clipboard.writeText(state.config.hook));
  $("command-copy").addEventListener("click", () => navigator.clipboard && navigator.clipboard.writeText($("command-text").textContent));
  for (const id of ["amount", "country", "trace"]) $(id).addEventListener("input", showCommand);
  renderSwitches();
  renderConsoleLinks();
  refreshStatus();
  refreshSwitches();
  loadBlobs();
  loadLinks();
  openBroker();
  setInterval(refreshStatus, 6000);
  setInterval(refreshSwitches, 8000);
  for (const origin of LAB_UIS) parent.postMessage({ type: "gravitee-lab:ready" }, origin);
}

start().catch((error) => { document.body.prepend(h("p", { class: "empty" }, `The app cannot start: ${error.message}`)); });

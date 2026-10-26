// MCPJam looks for Ollama at 127.0.0.1:11434: the browser lists the models from there, then the server calls the same
// address. Inside the container that address is the container itself, so this passes it on to Ollama on the host.
const net = require("node:net");

net.createServer((client) => {
  const ollama = net.connect(11434, "host.docker.internal");
  client.pipe(ollama).pipe(client);
  client.on("error", () => ollama.destroy());
  ollama.on("error", () => client.destroy());
}).listen(11434, "127.0.0.1");

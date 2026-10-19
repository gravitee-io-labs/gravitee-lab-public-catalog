"""The server as the container runs it: `python server.py` on a real port, then a real SIGTERM."""
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

from mcp import Client

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "demo-admin-token"


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_until_healthy(port, process, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"the server exited with {process.returncode}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as answer:
                return answer.read()
        except OSError:
            time.sleep(0.2)
    raise AssertionError("the server did not answer /health")


def post(port, path, body=None, headers=None):
    """One raw POST: the status, the headers and the body of the answer, whatever the status. The SDK refuses a name or
    an origin in plain text: that body is None."""
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST", headers=headers or {},
                                     data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=5) as answer:
            return answer.status, answer.headers, json.loads(answer.read())
    except urllib.error.HTTPError as refusal:
        text = refusal.read()
        refusal.close()
        return refusal.code, refusal.headers, json.loads(text) if text.startswith(b"{") else None


class Process(unittest.TestCase):
    def test_it_serves_on_http_port_and_stops_cleanly_on_sigterm(self):
        port = free_port()
        process = subprocess.Popen([sys.executable, "server.py"], cwd=APP, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True,
                                   env={**os.environ, "HTTP_PORT": str(port), "ADMIN_TOKEN": TOKEN})
        try:
            self.assertEqual(wait_until_healthy(port, process), b'{"status":"ok"}')
            asyncio.run(self.ask(port))
            self.check_the_transport(port)
            self.check_the_names(port)
            self.check_the_admin_route(port)
            process.send_signal(signal.SIGTERM)
            # uvicorn finishes its shutdown, then raises the signal again: only as PID 1, as in a container, is the
            # exit code 0, anywhere else the process ends "by SIGTERM"
            self.assertIn(process.wait(timeout=15), (0, -signal.SIGTERM))
        finally:
            if process.poll() is None:
                process.kill()
            output = process.stdout.read()
            process.stdout.close()
        self.assertIn("Application shutdown complete", output)
        self.assertIn("tools/call get_balance -> ok", output)
        self.assertIn("tools/call get_balance -> tool error", output)
        for echoed in ("ACC-1002", "ACC-9999", "Terminating session", "Error executing tool"):
            self.assertNotIn(echoed, output)

    def check_the_transport(self, port):
        """Stateless and plain JSON, as the gateway and the traffic generator need: the options reach the real server."""
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "get_balance", "arguments": {"account_id": "ACC-1002"}}}
        status, headers, body = post(port, "/", call, {"Content-Type": "application/json",
                                                       "Accept": "application/json, text/event-stream"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertIsNone(headers["Mcp-Session-Id"])
        self.assertEqual(body["result"]["structuredContent"]["balance"], 15300)

    def check_the_names(self, port):
        """The names it is reached by reach the real server: this machine's, not a hostile page's."""
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        self.assertEqual(post(port, "/", call, {**headers, "Host": f"localhost:{port}"})[0], 200)
        self.assertEqual(post(port, "/", call, {**headers, "Host": f"rebind.example:{port}"})[0], 421)
        self.assertEqual(post(port, "/", call, {**headers, "Origin": "http://evil.example"})[0], 403)
        self.assertEqual(post(port, "/", call, {**headers, "Content-Type": "text/plain"})[0], 400)

    def check_the_admin_route(self, port):
        self.assertEqual(post(port, "/admin/reset")[0], 403)
        self.assertEqual(post(port, "/admin/reset", headers={"X-Admin-Token": "wrong"})[0], 403)
        self.assertEqual(post(port, "/admin/reset", headers={"X-Admin-Token": TOKEN})[::2], (200, {"status": "reset"}))

    async def ask(self, port):
        url = f"http://127.0.0.1:{port}/"
        for mode, negotiated in (("legacy", "2025-11-25"), ("2026-07-28", "2026-07-28")):
            async with Client(url, mode=mode) as c:
                self.assertEqual(c.protocol_version, negotiated)
        async with Client(url) as c:
            result = await c.call_tool("get_balance", {"account_id": "ACC-1002"})
            unknown = await c.call_tool("get_balance", {"account_id": "ACC-9999"})
        self.assertEqual(result.structured_content["balance"], 15300)
        self.assertTrue(unknown.is_error)


if __name__ == "__main__":
    unittest.main()

"""What every test of the app starts from: the app over the fakes, and a browser-like client for it."""

import unittest
from urllib.parse import urlsplit

import httpx

from server import build_app
from tests.fakes import World


class AppCase(unittest.IsolatedAsyncioTestCase):
    settings_overrides: dict = {}

    async def asyncSetUp(self) -> None:
        self.world = World()
        self.app = build_app(self.world.settings(**self.settings_overrides), self.world.clients())
        self.web = self.app.state.web
        self.http = self.browser()
        self.addAsyncCleanup(self.http.aclose)
        self.addAsyncCleanup(self.web.clients.aclose)

    def browser(self, **headers: str) -> httpx.AsyncClient:
        """A client with its own cookie jar that sends the Origin a browser sends from the app's own page."""
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url="http://localhost",
            headers={"Origin": "http://localhost", "X-Requested-With": "acme-bank", **headers},
        )

    async def go(self, url: str, client: httpx.AsyncClient | None = None, **headers: str) -> httpx.Response:
        """A navigation of the browser (a window opened by the page, the redirect of a server): it sends no Origin and none of the page's own headers, only what the
        browser adds to a request of its own, which `headers` says (Sec-Fetch-Site)."""
        client = client or self.http
        request = client.build_request("GET", url, headers=headers)
        for name in ("origin", "x-requested-with"):
            request.headers.pop(name, None)
        return await client.send(request)

    async def sign_in(self, persona: str = "alice", client: httpx.AsyncClient | None = None, as_user: str | None = None,
                      outcome: str = "signed-in") -> httpx.Response:
        """Signs a person in as the page does, from the first step to the last: the window goes to /login, which sends it to the login page of Access Management (the
        fake signs `as_user` in there, else the person the app asked for), which sends it back to /callback with a code, which sends it on to the small page that says
        how the sign-in ended. Returns that answer."""
        client = client or self.http
        login = await self.go(f"/login?persona={persona}", client, **{"Sec-Fetch-Site": "same-origin"})
        self.assertEqual(login.status_code, 302, login.text)
        self.world.am.signs_in_as = as_user
        async with httpx.AsyncClient(transport=self.world.transport) as am:
            page = await am.get(login.headers["location"])
        self.assertEqual(page.status_code, 302, page.text)
        back = urlsplit(page.headers["location"])
        done = await self.go(f"{back.path}?{back.query}", client, **{"Sec-Fetch-Site": "same-site"})
        self.assertEqual((done.status_code, done.headers["location"]), (303, f"/sign-in-done.html?outcome={outcome}"), done.text)
        return done

    async def chat(self, message: str = "Show my accounts and balances", **extra) -> dict:
        response = await self.http.post("/api/chat", json={"message": message, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

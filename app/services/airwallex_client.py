"""Airwallex sandbox REST client. Conventions from the builder guide:
- base https://api.sandbox.airwallex.com, paths start /api/v1
- login with x-client-id / x-api-key headers -> 30-min bearer token
- amounts are MAJOR units (100 = one hundred dollars), never cents
- stable UUID request_id per operation; new UUID for a new operation
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field

import httpx

BASE_URL = os.getenv("AWX_BASE_URL", "https://api.sandbox.airwallex.com")


def new_request_id() -> str:
    return str(uuid.uuid4())


@dataclass
class AirwallexClient:
    client_id: str = field(default_factory=lambda: os.getenv("AWX_CLIENT_ID", ""))
    api_key: str = field(default_factory=lambda: os.getenv("AWX_API_KEY", ""))
    base_url: str = BASE_URL
    _token: str = ""
    _token_at: float = 0.0

    def _http(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=30.0)

    def login(self) -> str:
        """Returns a bearer token (cached ~25 min; tokens live 30 min)."""
        if self._token and time.time() - self._token_at < 25 * 60:
            return self._token
        if not self.client_id or not self.api_key or "put_" in self.client_id:
            raise RuntimeError("sandbox credentials missing — copy .env.example to .env")
        with self._http() as c:
            r = c.post(
                "/api/v1/authentication/login",
                headers={"x-client-id": self.client_id, "x-api-key": self.api_key},
            )
            r.raise_for_status()
            data = r.json()
        token = data.get("token") or data.get("access_token") or ""
        if not token:
            raise RuntimeError(f"login returned no token: {str(data)[:160]}")
        self._token, self._token_at = token, time.time()
        return token

    def _auth(self, extra: dict | None = None) -> dict:
        h = {"Authorization": f"Bearer {self.login()}", "Content-Type": "application/json"}
        if extra:
            h.update(extra)
        return h

    def get(self, path: str, *, on_behalf_of: str = "", params: dict | None = None) -> dict:
        extra = {"x-on-behalf-of": on_behalf_of} if on_behalf_of else None
        with self._http() as c:
            r = c.get(path, headers=self._auth(extra), params=params)
            r.raise_for_status()
            return r.json()

    def post(self, path: str, body: dict, *, on_behalf_of: str = "", request_id: str = "") -> dict:
        body = {**body, "request_id": request_id or new_request_id()}
        extra = {"x-on-behalf-of": on_behalf_of} if on_behalf_of else None
        with self._http() as c:
            r = c.post(path, headers=self._auth(extra), json=body)
            r.raise_for_status()
            return r.json()

    # --- convenience wrappers used by the kits ---
    def balances(self) -> dict:
        return self.get("/api/v1/balances/current")

    def global_accounts(self) -> dict:
        return self.get("/api/v1/global_accounts")

    def fx_quote(self, buy_currency: str, sell_currency: str, buy_amount: str) -> dict:
        return self.post(
            "/api/v1/fx/quotes/create",
            {"buy_currency": buy_currency, "sell_currency": sell_currency, "buy_amount": buy_amount},
        )

    def fx_convert(self, buy_currency: str, sell_currency: str, buy_amount: str, quote_id: str = "") -> dict:
        body: dict = {"buy_currency": buy_currency, "sell_currency": sell_currency, "buy_amount": buy_amount}
        if quote_id:
            body["quote_id"] = quote_id  # single-use: book once, fresh quote to convert again
        return self.post("/api/v1/fx/conversions/create", body)

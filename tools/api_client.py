"""Client for the integration layer. Tools never know the ERP exists."""
from __future__ import annotations

import contextvars
from functools import lru_cache

import httpx

import settings

# Set by the orchestrator per workflow run so every downstream call is traceable.
correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)


class IntegrationError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _client() -> httpx.Client:
    headers = {
        "client_id": settings.INTEGRATION_CLIENT_ID,
        "client_secret": settings.INTEGRATION_CLIENT_SECRET,
    }
    if settings.INTEGRATION_URL:
        return httpx.Client(base_url=settings.INTEGRATION_URL, headers=headers, timeout=10)
    from fastapi.testclient import TestClient

    from integration.api import app
    return TestClient(app, headers=headers)


def _headers() -> dict:
    cid = correlation_id.get()
    return {"x-correlation-id": cid} if cid else {}


def _check(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise IntegrationError(f"{r.request.method} {r.request.url.path} -> {r.status_code}: {detail}")
    return r.json()


def get(path: str, **params) -> dict:
    return _check(_client().get(path, params=params or None, headers=_headers()))


def post(path: str, body: dict) -> dict:
    return _check(_client().post(path, json=body, headers=_headers()))

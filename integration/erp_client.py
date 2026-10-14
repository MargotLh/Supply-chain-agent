"""HTTP client the integration layer uses to reach the ERP.

If ERP_URL is set we go over the network; otherwise the ERP app is mounted
in-process, so the whole stack runs with `python run_demo.py` and no servers.
"""
from functools import lru_cache

import httpx

import settings


@lru_cache(maxsize=1)
def erp() -> httpx.Client:
    if settings.ERP_URL:
        return httpx.Client(base_url=settings.ERP_URL, timeout=10)
    from fastapi.testclient import TestClient

    from mock_erp.api import app
    return TestClient(app)

"""Integration layer - a stand-in for MuleSoft Anypoint.

Mirrors API-led connectivity:
  * System API  (/api/v1/system/...)  - thin wrapper over the legacy ERP, translates
    SAP-style fields into a canonical model.
  * Process API (/api/v1/process/...) - composes system calls into business operations
    (e.g. "inventory options for an order").

Also applies the cross-cutting policies MuleSoft would: client-id enforcement,
correlation-id propagation, and request logging. Agents/MCP tools only ever talk
to this layer, so the ERP can change (or be replaced) without touching the agents.

Run standalone:  uvicorn integration.api:app --port 8002
"""
from __future__ import annotations

import logging
import uuid
from datetime import date

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

import settings
from integration.erp_client import erp

log = logging.getLogger("integration")
app = FastAPI(title="Integration Layer (MuleSoft stand-in)", version="1.0")


# --- Policies ------------------------------------------------------------------------

def client_id_enforcement(
    client_id: str | None = Header(default=None, alias="client_id"),
    client_secret: str | None = Header(default=None, alias="client_secret"),
):
    if client_id != settings.INTEGRATION_CLIENT_ID or client_secret != settings.INTEGRATION_CLIENT_SECRET:
        raise HTTPException(401, "Invalid client credentials")


@app.middleware("http")
async def correlation_id(request: Request, call_next):
    cid = request.headers.get("x-correlation-id") or str(uuid.uuid4())
    request.state.cid = cid
    response = await call_next(request)
    response.headers["x-correlation-id"] = cid
    log.info("%s %s cid=%s -> %s", request.method, request.url.path, cid, response.status_code)
    return response


secured = [Depends(client_id_enforcement)]


def _erp_get(path: str, **params):
    r = erp().get(path, params=params or None)
    if r.status_code == 404:
        raise HTTPException(404, r.json().get("detail", "Not found"))
    r.raise_for_status()
    return r.json()


def _erp_post(path: str, body: dict):
    r = erp().post(path, json=body)
    if r.status_code == 404:
        raise HTTPException(404, r.json().get("detail", "Not found"))
    r.raise_for_status()
    return r.json()


# --- System API: ERP -> canonical model --------------------------------------------

@app.get("/api/v1/system/orders/{order_id}", dependencies=secured)
def order(order_id: str):
    o = _erp_get(f"/erp/orders/{order_id}")
    today = date.fromisoformat(o["SYSTEM_DATE"])
    promised = date.fromisoformat(o["PROMISED_DT"])
    return {
        "order_id": o["ORD_NO"],
        "customer": {"id": o["KUNNR"], "name": o["CUST_NAME"], "tier": o["CUST_TIER"]},
        "sku": o["MATNR"],
        "description": o["MAKTX"],
        "quantity": o["MENGE"],
        "source_warehouse": o["WERKS"],
        "promised_date": o["PROMISED_DT"],
        "days_to_promise": (promised - today).days,
        "order_value_gbp": o["NETWR_GBP"],
        "status": o["STATUS"],
        "actions": o["ACTIONS"],
    }


@app.get("/api/v1/system/inventory/{sku}", dependencies=secured)
def inventory(sku: str):
    s = _erp_get("/erp/stock", matnr=sku)
    return {
        "sku": sku,
        "locations": [
            {
                "warehouse_id": i["WERKS"],
                "warehouse_name": i["WERKS_NAME"],
                "available_units": i["LABST"],
                "reroute_cost_gbp": i["REROUTE_COST_GBP"],
                "transit_days": i["TRANSIT_D"],
            }
            for i in s["ITEMS"]
        ],
    }


@app.get("/api/v1/system/suppliers/{sku}", dependencies=secured)
def suppliers(sku: str):
    v = _erp_get("/erp/vendors", matnr=sku)
    return {
        "sku": sku,
        "suppliers": [
            {
                "supplier_id": i["LIFNR"],
                "supplier": i["NAME1"],
                "available_units": i["AVAIL_QTY"],
                "lead_time_days": i["LEAD_TIME_D"],
                "extra_cost": i["EXTRA_COST_GBP"],
            }
            for i in v["ITEMS"]
        ],
    }


@app.get("/api/v1/system/shipments/{order_id}", dependencies=secured)
def shipment(order_id: str):
    s = _erp_get(f"/erp/shipments/{order_id}")
    return {
        "order_id": s["ORD_NO"],
        "shipment_id": s["TKNUM"],
        "carrier": s["CARRIER"],
        "original_eta": s["ORIG_ETA"],
        "current_eta": s["CURR_ETA"],
        "delay_reason": s["DELAY_RSN"] or None,
    }


class OrderUpdate(BaseModel):
    action: str
    detail: str = ""
    extra_cost_gbp: float = 0
    approval_id: str | None = None


@app.post("/api/v1/system/orders/{order_id}/actions", dependencies=secured)
def update_order(order_id: str, body: OrderUpdate, request: Request):
    r = _erp_post(f"/erp/orders/{order_id}/actions", {
        "ACTION": body.action,
        "DETAIL": body.detail,
        "EXTRA_COST_GBP": body.extra_cost_gbp,
        "APPROVAL_REF": body.approval_id,
        "CORRELATION_ID": request.state.cid,
    })
    return {"order_id": r["ORD_NO"], "status": r["STATUS"]}


class OpsMessage(BaseModel):
    text: str
    channel: str = "ops-exceptions"


@app.post("/api/v1/system/notifications", dependencies=secured)
def notify(body: OpsMessage, request: Request):
    r = _erp_post("/erp/messages", {"CHANNEL": body.channel, "TEXT": body.text,
                                     "CORRELATION_ID": request.state.cid})
    return {"message_id": r["MSG_ID"], "channel": r["CHANNEL"], "delivered": True}


# --- Event API: ERP outbox -> canonical events --------------------------------------

@app.get("/api/v1/events", dependencies=secured)
def events(after: int = 0):
    raw = _erp_get("/erp/outbox", after=after)["ITEMS"]
    return {
        "events": [
            {
                "sequence": e["EVT_ID"],
                "type": e["EVT_TYPE"],
                "order_id": e["ORD_NO"],
                "delay_days": e["DELAY_D"],
                "reason": e["RSN"],
                "occurred_at": e["TS"],
                "source": "ERP",
            }
            for e in raw
        ]
    }


# --- Process API: composed business view ---------------------------------------------

@app.get("/api/v1/process/orders/{order_id}/context", dependencies=secured)
def order_context(order_id: str):
    """One call that assembles what an investigator needs (order + shipment)."""
    return {"order": order(order_id), "shipment": shipment(order_id)}

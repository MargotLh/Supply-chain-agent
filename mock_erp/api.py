"""Mock legacy ERP / TMS.

Deliberately "legacy-shaped": SAP-style field names (MATNR, WERKS, LABST, LIFNR...),
no auth model of its own and no canonical schema. Agents never call this directly;
the integration layer (MuleSoft stand-in) wraps it.

Run standalone:  uvicorn mock_erp.api:app --port 8001
"""
from __future__ import annotations

import copy
import json
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DATA_FILE = Path(__file__).with_name("data.json")

_lock = threading.Lock()
_state: dict = {}


def reset_state() -> None:
    """Reload the seed data (used by tests and the demo)."""
    global _state
    with _lock:
        _state = json.loads(DATA_FILE.read_text())
        _state["outbox"] = []
        _state["messages"] = []


reset_state()

app = FastAPI(title="Mock Legacy ERP / TMS", version="1.0")


def _order(ord_no: str) -> dict:
    order = _state["orders"].get(ord_no)
    if order is None:
        raise HTTPException(404, f"ORD_NO {ord_no} not found")
    return order


@app.get("/erp/orders/{ord_no}")
def get_order(ord_no: str):
    return {"SYSTEM_DATE": _state["SYSTEM_DATE"], **_order(ord_no)}


@app.get("/erp/stock")
def get_stock(matnr: str):
    return {"MATNR": matnr, "ITEMS": _state["stock"].get(matnr, [])}


@app.get("/erp/vendors")
def get_vendors(matnr: str):
    return {"MATNR": matnr, "ITEMS": _state["vendors"].get(matnr, [])}


@app.get("/erp/shipments/{ord_no}")
def get_shipment(ord_no: str):
    shp = _state["shipments"].get(ord_no)
    if shp is None:
        raise HTTPException(404, f"No shipment for ORD_NO {ord_no}")
    return {"ORD_NO": ord_no, **shp}


class ActionIn(BaseModel):
    ACTION: str
    DETAIL: str = ""
    EXTRA_COST_GBP: float = 0
    APPROVAL_REF: str | None = None
    CORRELATION_ID: str | None = None


@app.post("/erp/orders/{ord_no}/actions")
def post_action(ord_no: str, body: ActionIn):
    with _lock:
        order = _order(ord_no)
        entry = {**body.model_dump(), "TS": datetime.now(timezone.utc).isoformat()}
        order["ACTIONS"].append(entry)
        order["STATUS"] = {
            "REROUTE_WAREHOUSE": "REROUTED",
            "ALTERNATIVE_SUPPLIER": "RESOURCED",
            "WAIT": "DELAYED_ACCEPTED",
            "HOLD": "ON_HOLD_PENDING_REVIEW",
        }.get(body.ACTION, order["STATUS"])
    return {"ORD_NO": ord_no, "STATUS": order["STATUS"], "ACTION_LOGGED": entry}


class MessageIn(BaseModel):
    CHANNEL: str = "ops-exceptions"
    TEXT: str
    CORRELATION_ID: str | None = None


@app.post("/erp/messages")
def post_message(body: MessageIn):
    with _lock:
        msg = {"MSG_ID": len(_state["messages"]) + 1, **body.model_dump(),
               "TS": datetime.now(timezone.utc).isoformat()}
        _state["messages"].append(msg)
    return msg


@app.get("/erp/messages")
def list_messages():
    return {"ITEMS": _state["messages"]}


# --- Event production (transactional outbox) -------------------------------------

class DelayIn(BaseModel):
    DELAY_D: int
    RSN: str = "Carrier reported delay"


@app.post("/erp/shipments/{ord_no}/delay")
def report_delay(ord_no: str, body: DelayIn):
    """The TMS records a carrier delay. As a side effect the ERP writes an
    ORDER_DELAYED event to its outbox - this is what starts the agent workflow."""
    with _lock:
        _order(ord_no)
        shp = _state["shipments"][ord_no]
        eta = date.fromisoformat(shp["ORIG_ETA"]) + timedelta(days=body.DELAY_D)
        shp["CURR_ETA"] = eta.isoformat()
        shp["DELAY_RSN"] = body.RSN
        evt = {
            "EVT_ID": len(_state["outbox"]) + 1,
            "EVT_TYPE": "ORDER_DELAYED",
            "ORD_NO": ord_no,
            "DELAY_D": body.DELAY_D,
            "RSN": body.RSN,
            "TS": datetime.now(timezone.utc).isoformat(),
        }
        _state["outbox"].append(evt)
    return evt


@app.get("/erp/outbox")
def read_outbox(after: int = 0):
    return {"ITEMS": [e for e in _state["outbox"] if e["EVT_ID"] > after]}


@app.post("/erp/_reset")
def _reset():
    reset_state()
    return {"ok": True}


def snapshot() -> dict:
    return copy.deepcopy(_state)

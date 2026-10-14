"""Orchestrator as a long-running service (used by docker-compose).

Polls the ERP outbox (via the integration layer) for ORDER_DELAYED events and
runs the agent workflow. Humans approve/reject through this API.

    uvicorn service:app --port 8000

    GET  /runs                         workflow runs
    GET  /approvals                    pending approvals
    POST /approvals/{id}/approve       {"approver": "...", "note": "..."}
    POST /approvals/{id}/reject
    GET  /audit?run_id=...             audit trail
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agents.orchestrator import Orchestrator
from events.order_delayed import ORDER_DELAYED, EventBus, OutboxListener
from governance.approvals import approvals
from governance.audit_log import audit

orchestrator = Orchestrator()
bus = EventBus()
bus.subscribe(ORDER_DELAYED, orchestrator.handle_event)
listener = OutboxListener(bus)


@asynccontextmanager
async def lifespan(_app):
    audit.subscribe(lambda e: print(e.line(), flush=True))
    t = threading.Thread(target=listener.run_forever, daemon=True)
    t.start()
    yield
    listener.stop()


app = FastAPI(title="Supply Chain Exception Orchestrator", lifespan=lifespan)


@app.get("/runs")
def runs():
    return [r.summary() for r in orchestrator.runs.values()]


@app.get("/approvals")
def pending():
    return [asdict(a) for a in approvals.pending()]


class Decision(BaseModel):
    approver: str
    note: str | None = None


def _decide(approval_id: str, approved: bool, d: Decision):
    run = next((r for r in orchestrator.runs.values() if r.approval_id == approval_id), None)
    if run is None:
        raise HTTPException(404, "Unknown approval")
    try:
        return orchestrator.resume(run.run_id, approved, d.approver, d.note).summary()
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/approvals/{approval_id}/approve")
def approve(approval_id: str, d: Decision):
    return _decide(approval_id, True, d)


@app.post("/approvals/{approval_id}/reject")
def reject(approval_id: str, d: Decision):
    return _decide(approval_id, False, d)


@app.get("/audit")
def audit_trail(run_id: str | None = None):
    entries = audit.for_run(run_id) if run_id else audit.entries
    return [asdict(e) for e in entries]

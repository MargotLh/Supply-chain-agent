"""Orchestrator Agent.

Receives ORDER_DELAYED, decides which specialists to call and in what order, and
gates execution on human approval when policy requires it:

    delay detected
      -> get order + shipment context
      -> Inventory Agent
      -> if no viable warehouse stock: Supplier Agent
      -> Decision Agent (scores WAIT / REROUTE / ALT SUPPLIER)
      -> if WAIT: notify ops
      -> elif cost > threshold: pause, request human approval
      -> else: Execution Agent

A run that pauses for approval is resumed with `resume(run_id, approved=...)`.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

import settings
from agents.base import Agent
from agents.decision_agent import DecisionAgent, Recommendation
from agents.execution_agent import ExecutionAgent
from agents.inventory_agent import InventoryAgent
from agents.supplier_agent import SupplierAgent
from events.order_delayed import OrderDelayedEvent
from governance.approvals import approvals
from tools.api_client import correlation_id


@dataclass
class WorkflowRun:
    run_id: str
    event: OrderDelayedEvent
    status: str = "RUNNING"   # RUNNING | AWAITING_APPROVAL | COMPLETED | REJECTED | FAILED
    order: dict | None = None
    shipment: dict | None = None
    inventory: dict | None = None
    suppliers: dict | None = None
    recommendation: Recommendation | None = None
    approval_id: str | None = None
    outcome: str | None = None
    path: list[str] = field(default_factory=list)  # which agents ran, in order

    def summary(self) -> dict:
        return {
            "run_id": self.run_id, "order_id": self.event.order_id, "status": self.status,
            "path": self.path, "approval_id": self.approval_id, "outcome": self.outcome,
            "recommendation": self.recommendation.to_dict() if self.recommendation else None,
        }


class Orchestrator(Agent):
    name = "Orchestrator"

    def __init__(self):
        super().__init__()
        self.inventory_agent = InventoryAgent()
        self.supplier_agent = SupplierAgent()
        self.decision_agent = DecisionAgent()
        self.execution_agent = ExecutionAgent()
        self.runs: dict[str, WorkflowRun] = {}
        self._lock = threading.Lock()

    # --- entry point: event handler ------------------------------------------------

    def handle_event(self, event: OrderDelayedEvent) -> WorkflowRun:
        run = WorkflowRun(run_id=f"RUN-{event.order_id}-{event.event_id[-4:]}", event=event)
        with self._lock:
            self.runs[run.run_id] = run
        token = correlation_id.set(run.run_id)
        try:
            self._investigate_and_decide(run)
        except Exception as exc:
            run.status, run.outcome = "FAILED", f"{type(exc).__name__}: {exc}"
            self.log(f"Workflow failed: {run.outcome}", event="WORKFLOW_FAILED")
            raise
        finally:
            correlation_id.reset(token)
        return run

    def _investigate_and_decide(self, run: WorkflowRun) -> None:
        e = run.event
        self.log(f"{e.type} received from {e.source}: order #{e.order_id} {e.delay_days} days late "
                 f"({e.reason})", event="EVENT_RECEIVED")

        run.order = self.tools.call("get_order", order_id=e.order_id)
        run.shipment = self.tools.call("get_shipment", order_id=e.order_id)
        o = run.order
        self.log(f"Context: {o['quantity']} x {o['sku']} for {o['customer']['name']} "
                 f"({o['customer']['tier']}), promised in {o['days_to_promise']} day(s)")

        self.log("Plan: check alternative inventory first", event="PLAN")
        run.path.append(self.inventory_agent.name)
        run.inventory = self.inventory_agent.run(o)

        if run.inventory["viable"]:
            self.log("Viable stock found -> skipping Supplier Agent", event="PLAN")
        else:
            self.log("No viable stock -> delegating to Supplier Agent", event="PLAN")
            run.path.append(self.supplier_agent.name)
            run.suppliers = self.supplier_agent.run(o)

        run.path.append(self.decision_agent.name)
        rec = run.recommendation = self.decision_agent.run(o, e.delay_days, run.inventory, run.suppliers)

        if rec.requires_approval:
            why = (f"Cost £{rec.extra_cost_gbp:,.0f} > £{settings.APPROVAL_THRESHOLD_GBP:,.0f} threshold"
                   if rec.extra_cost_gbp > settings.APPROVAL_THRESHOLD_GBP
                   else "Recommendation differs from the lowest-cost option")
            self.log(f"{why} -> pausing for human approval", event="PLAN")
            ticket = approvals.request(order_id=o["order_id"], action=rec.action,
                                       extra_cost_gbp=rec.extra_cost_gbp, rationale=rec.rationale,
                                       requested_by=self.name, correlation_id=run.run_id)
            run.approval_id, run.status = ticket.id, "AWAITING_APPROVAL"
        elif rec.action == "WAIT":
            self.log("Best option is to wait -> record decision in ERP + notify ops (no cost, no approval)", event="PLAN")
            self._execute(run)
        else:
            self.log(f"Cost £{rec.extra_cost_gbp:,.0f} within autonomous limit "
                     f"(£{settings.APPROVAL_THRESHOLD_GBP:,.0f}) -> executing", event="PLAN")
            self._execute(run)

    # --- human-in-the-loop resume ---------------------------------------------------

    def resume(self, run_id: str, approved: bool, approver: str, note: str | None = None) -> WorkflowRun:
        run = self.runs[run_id]
        if run.status != "AWAITING_APPROVAL":
            raise ValueError(f"{run_id} is {run.status}, not awaiting approval")
        token = correlation_id.set(run.run_id)
        try:
            approvals.decide(run.approval_id, approved, approver, note)
            if approved:
                self._execute(run)
            else:
                run.path.append(self.execution_agent.name)
                self.execution_agent.hold(run.order, run.recommendation, run.approval_id, note)
                run.status, run.outcome = "REJECTED", "Order placed on hold; ops notified"
                self.log("Workflow closed: recommendation rejected", event="WORKFLOW_DONE")
        finally:
            correlation_id.reset(token)
        return run

    def _execute(self, run: WorkflowRun) -> None:
        rec = run.recommendation
        run.path.append(self.execution_agent.name)
        if rec.action == "WAIT":
            self.execution_agent.tools.call("send_operations_message", message=(
                f"[Order #{run.order['order_id']} | {run.order['customer']['name']}] "
                f"{run.event.delay_days}-day delay accepted. {rec.rationale}"))
            self.execution_agent.tools.call("update_order", order_id=run.order["order_id"], action="WAIT",
                                            detail=rec.rationale)
        else:
            self.execution_agent.execute(run.order, rec, run.approval_id)
        run.status = "COMPLETED"
        run.outcome = f"{rec.action}{f' via {rec.target}' if rec.target else ''} (£{rec.extra_cost_gbp:,.0f})"
        self.log(f"Workflow complete: {run.outcome}", event="WORKFLOW_DONE")

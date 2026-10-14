"""Human-in-the-loop approval tickets.

A ticket is bound to one order, one action and one cost ceiling. The tool gateway
checks the ticket before letting update_order() through, so an approval for
"reroute order 1842 for £2,400" can't be reused for a different order or a
more expensive action.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from governance.audit_log import audit


@dataclass
class ApprovalRequest:
    id: str
    order_id: str
    action: str
    extra_cost_gbp: float
    rationale: str
    requested_by: str
    correlation_id: str | None
    status: str = "PENDING"        # PENDING | APPROVED | REJECTED
    decided_by: str | None = None
    note: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def covers(self, order_id: str, action: str, extra_cost_gbp: float) -> bool:
        return (self.status == "APPROVED" and self.order_id == order_id
                and self.action == action and extra_cost_gbp <= self.extra_cost_gbp)


class ApprovalStore:
    def __init__(self):
        self._items: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()

    def request(self, *, order_id: str, action: str, extra_cost_gbp: float, rationale: str,
                requested_by: str, correlation_id: str | None) -> ApprovalRequest:
        req = ApprovalRequest(f"APR-{uuid.uuid4().hex[:6].upper()}", order_id, action,
                              extra_cost_gbp, rationale, requested_by, correlation_id)
        with self._lock:
            self._items[req.id] = req
        audit.record(requested_by, "APPROVAL_REQUESTED",
                     f"requested human approval {req.id}: {action} on #{order_id} (£{extra_cost_gbp:,.0f})",
                     correlation_id, approval_id=req.id)
        return req

    def decide(self, approval_id: str, approved: bool, approver: str, note: str | None = None) -> ApprovalRequest:
        with self._lock:
            req = self._items.get(approval_id)
            if req is None:
                raise KeyError(approval_id)
            if req.status != "PENDING":
                raise ValueError(f"{approval_id} already {req.status}")
            req.status = "APPROVED" if approved else "REJECTED"
            req.decided_by, req.note = approver, note
        audit.record(f"human:{approver}", f"APPROVAL_{req.status}",
                     f"{'approved' if approved else 'rejected'} {approval_id}" + (f" ({note})" if note else ""),
                     req.correlation_id, approval_id=approval_id)
        return req

    def get(self, approval_id: str | None) -> ApprovalRequest | None:
        return self._items.get(approval_id) if approval_id else None

    def pending(self) -> list[ApprovalRequest]:
        return [r for r in self._items.values() if r.status == "PENDING"]

    def all(self) -> list[ApprovalRequest]:
        return list(self._items.values())


approvals = ApprovalStore()

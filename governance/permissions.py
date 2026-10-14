"""Least-privilege tool access + policy enforcement at the tool boundary.

Agents don't get raw tool functions. They get a ToolGateway that:
  1. checks the agent's role is allowed to call that tool,
  2. runs any tool-specific policy (e.g. approval required above a cost threshold),
  3. writes every call, result and denial to the audit log.

Policy lives here, not in agent prompts/logic, so a misbehaving or manipulated
agent still can't execute an expensive action.
"""
from __future__ import annotations

from typing import Any, Callable

import settings
from governance.approvals import approvals
from governance.audit_log import audit
from tools import TOOLS
from tools.api_client import correlation_id

ROLE_PERMISSIONS: dict[str, set[str]] = {
    # reads the triggering context, delegates everything else
    "Orchestrator":    {"get_order", "get_shipment"},
    # ✓ read inventory   ✗ update orders
    "Inventory Agent": {"check_inventory"},
    "Supplier Agent":  {"find_alternative_supplier"},
    # ✓ recommend action ✗ execute anything (pure reasoning, no tools)
    "Decision Agent":  set(),
    # ✓ update order - only within policy (approval above threshold)
    "Execution Agent": {"update_order", "send_operations_message"},
    # external MCP clients (Claude Desktop, Agentforce...) get read-only access by default
    "MCP Client":      {"get_order", "get_shipment", "check_inventory", "find_alternative_supplier"},
}


class PermissionDenied(Exception):
    def __init__(self, agent: str, tool: str, reason: str):
        super().__init__(f"{agent} may not call {tool}: {reason}")
        self.agent, self.tool, self.reason = agent, tool, reason


def _update_order_policy(kwargs: dict) -> None:
    cost = float(kwargs.get("extra_cost_gbp", 0))
    if cost <= settings.APPROVAL_THRESHOLD_GBP:
        return
    ticket = approvals.get(kwargs.get("approval_id"))
    if ticket is None:
        raise PermissionError(f"£{cost:,.0f} exceeds £{settings.APPROVAL_THRESHOLD_GBP:,.0f} threshold; "
                              "human approval required")
    if not ticket.covers(str(kwargs["order_id"]), kwargs["action"], cost):
        raise PermissionError(f"approval {ticket.id} ({ticket.status}) does not cover this action")


POLICIES: dict[str, Callable[[dict], None]] = {
    "update_order": _update_order_policy,
}


def _fmt_args(kwargs: dict) -> str:
    def short(v):
        return repr(v[:40] + "…") if isinstance(v, str) and len(v) > 40 else repr(v)
    return ", ".join(f"{k}={short(v)}" for k, v in kwargs.items() if v not in (None, "", 0))


class ToolGateway:
    def __init__(self, agent: str):
        if agent not in ROLE_PERMISSIONS:
            raise ValueError(f"Unknown agent role {agent!r}")
        self.agent = agent

    @property
    def allowed(self) -> set[str]:
        return ROLE_PERMISSIONS[self.agent]

    def call(self, tool: str, **kwargs) -> Any:
        cid = correlation_id.get()
        call_str = f"{tool}({_fmt_args(kwargs)})"
        if tool not in self.allowed:
            audit.record(self.agent, "TOOL_DENIED", f"✗ DENIED {call_str} - not in role permissions", cid)
            raise PermissionDenied(self.agent, tool, "not in role permissions")
        if tool in POLICIES:
            try:
                POLICIES[tool](kwargs)
            except PermissionError as e:
                audit.record(self.agent, "TOOL_DENIED", f"✗ DENIED {call_str} - {e}", cid)
                raise PermissionDenied(self.agent, tool, str(e)) from e
        audit.record(self.agent, "TOOL_CALL", f"called {call_str}", cid, tool=tool, args=kwargs)
        result = TOOLS[tool](**kwargs)
        audit.record(self.agent, "TOOL_RESULT", f"  ↳ {tool} ok", cid, tool=tool, result=result)
        return result

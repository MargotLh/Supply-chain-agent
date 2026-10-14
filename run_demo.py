"""End-to-end demo - no servers, no API keys needed.

    python run_demo.py                      # order 1842, interactive approval
    python run_demo.py --scenario all       # all four scenarios
    python run_demo.py --scenario 1843 --decision reject

Each scenario: the ERP records a carrier delay -> ORDER_DELAYED lands in its outbox
-> the listener publishes it -> the Orchestrator runs the agents -> human approval
if needed -> ERP updated + ops notified.
"""
from __future__ import annotations

import argparse
import sys

from agents.orchestrator import Orchestrator
from events.order_delayed import ORDER_DELAYED, EventBus, OutboxListener, simulate_erp_delay
from governance.audit_log import AuditEntry, audit
import settings
from tools import api_client

SCENARIOS = {
    "1842": (4, "Port congestion at Felixstowe"),   # stock elsewhere, expensive -> approval
    "1843": (6, "Vessel rolled to next sailing"),   # no stock -> alt supplier -> approval
    "1844": (3, "Vehicle breakdown"),               # cheap reroute -> autonomous
    "1845": (1, "Missed collection slot"),          # waiting is cheapest -> no action
}

C = {"Orchestrator": "\033[95m", "Inventory Agent": "\033[94m", "Supplier Agent": "\033[96m",
     "Decision Agent": "\033[93m", "Execution Agent": "\033[92m"}
DIM, BOLD, RED, RESET = "\033[2m", "\033[1m", "\033[91m", "\033[0m"


def printer(e: AuditEntry) -> None:
    if e.event == "TOOL_RESULT":
        return
    color = RED if e.event == "TOOL_DENIED" else C.get(e.actor, BOLD)
    print(f"{color}{e.line()}{RESET}")


def ask_human(run) -> tuple[bool, str | None]:
    rec = run.recommendation
    print(f"\n{BOLD}┌─ HUMAN APPROVAL REQUIRED ({run.approval_id}) {'─' * 30}{RESET}")
    print(f"│ Order #{run.order['order_id']} - {run.order['customer']['name']} ({run.order['customer']['tier']})")
    print(f"│ Agent recommendation: {rec.action} {rec.target or ''}")
    print(f"│ Additional cost: £{rec.extra_cost_gbp:,.0f}")
    print(f"│ {rec.rationale}")
    print(f"{BOLD}└{'─' * 70}{RESET}")
    while True:
        ans = input("APPROVE / REJECT? [a/r] ").strip().lower()
        if ans in ("a", "approve"):
            return True, None
        if ans in ("r", "reject"):
            return False, input("Reason (optional): ").strip() or None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", default="1842", choices=[*SCENARIOS, "all"])
    p.add_argument("--decision", default="prompt", choices=["prompt", "approve", "reject"])
    args = p.parse_args()

    if settings.INTEGRATION_URL is None:
        from mock_erp.api import reset_state
        reset_state()

    audit.subscribe(printer)
    orchestrator = Orchestrator()
    bus, runs = EventBus(), []
    bus.subscribe(ORDER_DELAYED, lambda evt: runs.append(orchestrator.handle_event(evt)))
    listener = OutboxListener(bus)
    listener.poll_once()  # skip anything already in the outbox
    runs.clear()

    for order_id in (SCENARIOS if args.scenario == "all" else [args.scenario]):
        days, reason = SCENARIOS[order_id]
        print(f"\n{BOLD}━━━ ERP: carrier reports order #{order_id} will be {days} day(s) late ━━━{RESET}")
        simulate_erp_delay(order_id, days, reason)
        listener.poll_once()
        run = runs[-1]

        if run.status == "AWAITING_APPROVAL":
            if args.decision == "prompt":
                approved, note = ask_human(run)
            else:
                approved, note = args.decision == "approve", "auto-decided by --decision flag"
                print(f"\n{BOLD}[human] {'APPROVE' if approved else 'REJECT'} {run.approval_id}{RESET}")
            orchestrator.resume(run.run_id, approved, approver="ops.manager", note=note)

        order = api_client.get(f"/api/v1/system/orders/{order_id}")
        print(f"{BOLD}→ Run {run.run_id}: {run.status} | path: {' → '.join(run.path)} | "
              f"ERP status: {order['status']}{RESET}")

    print(f"\n{DIM}Full audit trail (JSONL): {audit.path}{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

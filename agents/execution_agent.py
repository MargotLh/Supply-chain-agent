from agents.base import Agent
from agents.decision_agent import Recommendation


class ExecutionAgent(Agent):
    """The only agent allowed to write to the ERP - and only within policy."""
    name = "Execution Agent"

    def execute(self, order: dict, rec: Recommendation, approval_id: str | None = None) -> dict:
        target = f" -> {rec.target}" if rec.target else ""
        result = self.tools.call(
            "update_order", order_id=order["order_id"], action=rec.action,
            detail=f"{rec.action}{target}: {rec.rationale}",
            extra_cost_gbp=rec.extra_cost_gbp, approval_id=approval_id,
        )
        approved = f" (approval {approval_id})" if approval_id else " (within autonomous limit)"
        self.tools.call("send_operations_message", message=(
            f"[Order #{order['order_id']} | {order['customer']['name']}] Delay handled: "
            f"{rec.action}{target}, extra cost £{rec.extra_cost_gbp:,.0f}{approved}. {rec.rationale}"))
        return result

    def hold(self, order: dict, rec: Recommendation, approval_id: str, reason: str | None) -> dict:
        result = self.tools.call(
            "update_order", order_id=order["order_id"], action="HOLD",
            detail=f"Recommendation {rec.action} rejected ({approval_id}): {reason or 'no reason given'}",
        )
        wait_late = next((o.days_late for o in rec.options if o.action == "WAIT"), "?")
        self.tools.call("send_operations_message", message=(
            f"[Order #{order['order_id']} | {order['customer']['name']}] Recommendation {rec.action} "
            f"(£{rec.extra_cost_gbp:,.0f}) was REJECTED. Order on hold for manual handling; "
            f"customer delivery currently {wait_late} day(s) late."))
        return result

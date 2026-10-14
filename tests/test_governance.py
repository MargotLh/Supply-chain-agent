import pytest

from governance.approvals import approvals
from governance.audit_log import audit
from governance.permissions import PermissionDenied, ToolGateway


def test_inventory_agent_cannot_update_orders():
    with pytest.raises(PermissionDenied):
        ToolGateway("Inventory Agent").call("update_order", order_id="1842", action="WAIT")
    assert audit.entries[-1].event == "TOOL_DENIED"


def test_decision_agent_has_no_tools():
    with pytest.raises(PermissionDenied):
        ToolGateway("Decision Agent").call("check_inventory", sku="SKU-4471")


def test_execution_agent_needs_approval_above_threshold():
    with pytest.raises(PermissionDenied, match="human approval required"):
        ToolGateway("Execution Agent").call("update_order", order_id="1842",
                                            action="REROUTE_WAREHOUSE", extra_cost_gbp=2400)


def test_execution_agent_can_act_below_threshold():
    r = ToolGateway("Execution Agent").call("update_order", order_id="1844",
                                            action="REROUTE_WAREHOUSE", extra_cost_gbp=350)
    assert r["status"] == "REROUTED"


def _ticket(order_id="1842", action="REROUTE_WAREHOUSE", cost=2400):
    return approvals.request(order_id=order_id, action=action, extra_cost_gbp=cost,
                             rationale="test", requested_by="test", correlation_id=None)


def test_pending_approval_is_not_enough():
    t = _ticket()
    with pytest.raises(PermissionDenied, match="does not cover"):
        ToolGateway("Execution Agent").call("update_order", order_id="1842", action="REROUTE_WAREHOUSE",
                                            extra_cost_gbp=2400, approval_id=t.id)


def test_rejected_approval_is_not_enough():
    t = _ticket()
    approvals.decide(t.id, approved=False, approver="ops")
    with pytest.raises(PermissionDenied):
        ToolGateway("Execution Agent").call("update_order", order_id="1842", action="REROUTE_WAREHOUSE",
                                            extra_cost_gbp=2400, approval_id=t.id)


@pytest.mark.parametrize("order_id,action,cost", [
    ("1843", "REROUTE_WAREHOUSE", 2400),     # different order
    ("1842", "ALTERNATIVE_SUPPLIER", 2400),  # different action
    ("1842", "REROUTE_WAREHOUSE", 5000),     # more expensive than approved
])
def test_approval_cannot_be_reused_for_something_else(order_id, action, cost):
    t = _ticket()
    approvals.decide(t.id, approved=True, approver="ops")
    with pytest.raises(PermissionDenied):
        ToolGateway("Execution Agent").call("update_order", order_id=order_id, action=action,
                                            extra_cost_gbp=cost, approval_id=t.id)


def test_approved_ticket_unlocks_exact_action():
    t = _ticket()
    approvals.decide(t.id, approved=True, approver="ops")
    r = ToolGateway("Execution Agent").call("update_order", order_id="1842", action="REROUTE_WAREHOUSE",
                                            extra_cost_gbp=2400, approval_id=t.id)
    assert r["status"] == "REROUTED"


def test_approval_cannot_be_decided_twice():
    t = _ticket()
    approvals.decide(t.id, approved=True, approver="ops")
    with pytest.raises(ValueError):
        approvals.decide(t.id, approved=False, approver="someone-else")

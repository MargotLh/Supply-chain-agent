from tools import api_client


def erp_status(order_id):
    return api_client.get(f"/api/v1/system/orders/{order_id}")["status"]


def test_event_comes_from_erp_outbox(raise_delay):
    evt = raise_delay("1842", 4, "Port congestion")
    assert (evt.type, evt.order_id, evt.delay_days, evt.source) == ("ORDER_DELAYED", "1842", 4, "ERP")


def test_expensive_reroute_waits_for_human_then_executes(orchestrator, raise_delay):
    run = orchestrator.handle_event(raise_delay("1842", 4))
    assert run.status == "AWAITING_APPROVAL"
    assert run.path == ["Inventory Agent", "Decision Agent"]          # supplier skipped: stock found
    assert (run.recommendation.action, run.recommendation.target) == ("REROUTE_WAREHOUSE", "WH-B")
    assert run.recommendation.extra_cost_gbp == 2400
    assert erp_status("1842") == "IN_TRANSIT"                         # nothing executed yet

    orchestrator.resume(run.run_id, approved=True, approver="ops.manager")
    assert run.status == "COMPLETED"
    assert erp_status("1842") == "REROUTED"


def test_rejection_puts_order_on_hold(orchestrator, raise_delay):
    run = orchestrator.handle_event(raise_delay("1842", 4))
    orchestrator.resume(run.run_id, approved=False, approver="ops.manager", note="budget freeze")
    assert run.status == "REJECTED"
    assert erp_status("1842") == "ON_HOLD_PENDING_REVIEW"


def test_no_stock_falls_back_to_supplier_agent(orchestrator, raise_delay):
    run = orchestrator.handle_event(raise_delay("1843", 6))
    assert run.path == ["Inventory Agent", "Supplier Agent", "Decision Agent"]
    assert (run.recommendation.action, run.recommendation.target) == ("ALTERNATIVE_SUPPLIER", "Supplier B")
    assert run.status == "AWAITING_APPROVAL"


def test_cheap_action_executes_autonomously(orchestrator, raise_delay):
    run = orchestrator.handle_event(raise_delay("1844", 3))
    assert run.status == "COMPLETED" and run.approval_id is None
    assert run.recommendation.extra_cost_gbp == 350
    assert erp_status("1844") == "REROUTED"


def test_short_delay_for_standard_customer_waits(orchestrator, raise_delay):
    run = orchestrator.handle_event(raise_delay("1845", 1))
    assert run.recommendation.action == "WAIT"
    assert run.status == "COMPLETED"
    assert erp_status("1845") == "DELAYED_ACCEPTED"


def test_ops_are_notified(orchestrator, raise_delay):
    from integration.erp_client import erp
    orchestrator.handle_event(raise_delay("1844", 3))
    msgs = erp().get("/erp/messages").json()["ITEMS"]
    assert any("#1844" in m["TEXT"] for m in msgs)


def test_every_call_is_traced_with_run_correlation_id(orchestrator, raise_delay):
    from governance.audit_log import audit
    run = orchestrator.handle_event(raise_delay("1844", 3))
    trail = audit.for_run(run.run_id)
    tools_called = [e.data["tool"] for e in trail if e.event == "TOOL_CALL"]
    assert tools_called == ["get_order", "get_shipment", "check_inventory",
                            "update_order", "send_operations_message"]
    from integration.erp_client import erp
    action = erp().get("/erp/orders/1844").json()["ACTIONS"][-1]
    assert action["CORRELATION_ID"] == run.run_id                 # propagated through the integration layer

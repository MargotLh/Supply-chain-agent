from agents.decision_agent import DecisionAgent


def order(tier="GOLD", days_to_promise=2):
    return {"order_id": "X", "customer": {"tier": tier}, "days_to_promise": days_to_promise}


def inv(*locs):
    return {"viable": [{"warehouse_id": w, "warehouse_name": w, "reroute_cost_gbp": c, "transit_days": t}
                       for w, c, t in locs]}


def test_picks_lowest_total_cost_including_late_penalties():
    rec = DecisionAgent().run(order("PLATINUM"), 4, inv(("WH-B", 2400, 1), ("WH-C", 3100, 2)), None)
    assert (rec.action, rec.target, rec.requires_approval) == ("REROUTE_WAREHOUSE", "WH-B", True)


def test_waits_when_mitigation_costs_more_than_delay():
    rec = DecisionAgent().run(order("STANDARD", 1), 1, inv(("WH-B", 600, 2)), None)
    assert rec.action == "WAIT" and not rec.requires_approval


def test_slow_option_still_incurs_penalty():
    # transit 4d with 2d slack -> 2d late: £100 + 2 x £600 = £1,300, still beats waiting (3 x £600 = £1,800)
    rec = DecisionAgent().run(order("GOLD", 2), 3, inv(("WH-C", 100, 4)), None)
    slow = next(o for o in rec.options if o.target == "WH-C")
    assert slow.days_late == 2 and slow.score == 1300
    assert rec.action == "REROUTE_WAREHOUSE"

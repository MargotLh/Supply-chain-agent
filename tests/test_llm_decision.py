"""Claude-backed Decision Agent: guardrails around the model's answer. No network calls."""
from types import SimpleNamespace

from agents.decision_agent import DecisionAgent
from agents.llm_reasoner import ClaudeReasoner, LLMChoice
from tests.test_decision_agent import inv, order


class FakeReasoner:
    model = "fake-claude"

    def __init__(self, answer):
        self.answer, self.seen = answer, None

    def choose(self, context):
        self.seen = context
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def cheap_reroute():
    # GOLD, 3 days late. Options sorted by score: [0] WH-B £350 on time, [1] WAIT £1,800
    return order("GOLD", 2), 3, inv(("WH-B", 350, 1)), None


def test_agreeing_with_rules_uses_claude_rationale_and_stays_autonomous():
    fake = FakeReasoner(LLMChoice(option_index=0, rationale="Reroute from WH-B; cheap and on time."))
    rec = DecisionAgent(reasoner=fake).run(*cheap_reroute())
    assert (rec.action, rec.target, rec.decided_by) == ("REROUTE_WAREHOUSE", "WH-B", "fake-claude")
    assert rec.rationale == "Reroute from WH-B; cheap and on time."
    assert not rec.requires_approval
    assert [o["index"] for o in fake.seen["options"]] == [0, 1]


def test_overriding_the_lowest_score_forces_human_approval():
    fake = FakeReasoner(LLMChoice(option_index=1, rationale="Customer prefers no changes; wait."))
    rec = DecisionAgent(reasoner=fake).run(*cheap_reroute())
    assert rec.action == "WAIT" and rec.extra_cost_gbp == 0
    assert rec.requires_approval


def test_invalid_index_falls_back_to_rules():
    rec = DecisionAgent(reasoner=FakeReasoner(LLMChoice(option_index=7, rationale="x"))).run(*cheap_reroute())
    assert (rec.action, rec.decided_by) == ("REROUTE_WAREHOUSE", "rules")


def test_api_error_falls_back_to_rules():
    rec = DecisionAgent(reasoner=FakeReasoner(TimeoutError("api down"))).run(*cheap_reroute())
    assert (rec.action, rec.decided_by, rec.requires_approval) == ("REROUTE_WAREHOUSE", "rules", False)


def test_claude_wait_override_pauses_workflow(orchestrator, raise_delay):
    # Order 1844 is a £350 reroute the rules would execute alone; Claude prefers to wait.
    orchestrator.decision_agent.reasoner = FakeReasoner(LLMChoice(option_index=1, rationale="Hold."))
    run = orchestrator.handle_event(raise_delay("1844", 3))
    assert run.status == "AWAITING_APPROVAL" and run.recommendation.action == "WAIT"


def test_reasoner_request_shape_and_refusal():
    calls = []

    def parse(**kw):
        calls.append(kw)
        return SimpleNamespace(stop_reason="refusal", parsed_output=None)

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    reasoner = ClaudeReasoner(client=client, model="claude-opus-5-5")
    try:
        reasoner.choose({"options": []})
        raise AssertionError("refusal should raise")
    except RuntimeError:
        pass
    kw = calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["output_format"] is LLMChoice
    assert kw["fallbacks"] == "default" and "thinking" not in kw

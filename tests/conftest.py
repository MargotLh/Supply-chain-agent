import os

os.environ["AUDIT_LOG_PATH"] = ""  # keep tests from writing logs/audit.jsonl
os.environ["DECISION_MODE"] = "rules"  # never call Claude from tests; LLM tests inject a fake

import pytest  # noqa: E402

from mock_erp.api import reset_state  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_erp():
    reset_state()
    yield


@pytest.fixture
def orchestrator():
    from agents.orchestrator import Orchestrator
    return Orchestrator()


@pytest.fixture
def raise_delay():
    """Simulate the ERP producing ORDER_DELAYED and return the event via the outbox listener."""
    from events.order_delayed import EventBus, OutboxListener, simulate_erp_delay

    def _raise(order_id, days, reason="test"):
        received = []
        bus = EventBus()
        bus.subscribe("ORDER_DELAYED", received.append)
        listener = OutboxListener(bus)
        simulate_erp_delay(order_id, days, reason)
        listener.poll_once()
        return received[-1]
    return _raise

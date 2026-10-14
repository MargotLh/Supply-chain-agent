"""ORDER_DELAYED events: schema, an in-process bus, and the ERP outbox listener.

Flow:  ERP writes event to its outbox  ->  OutboxListener polls the integration
layer's event API  ->  publishes onto EventBus  ->  Orchestrator handler runs.

No Kafka needed for the demo; the bus/listener interface is the seam where
Kafka, Anypoint MQ or Salesforce Platform Events would plug in.

CLI - simulate the ERP raising a delay:
    python -m events.order_delayed --order 1842 --days 4
"""
from __future__ import annotations

import argparse
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

ORDER_DELAYED = "ORDER_DELAYED"


@dataclass(frozen=True)
class OrderDelayedEvent:
    order_id: str
    delay_days: int
    reason: str
    source: str = "ERP"
    occurred_at: str = ""
    sequence: int = 0
    type: str = ORDER_DELAYED
    event_id: str = field(default_factory=lambda: f"EVT-{uuid.uuid4().hex[:8]}")

    @classmethod
    def from_api(cls, e: dict) -> "OrderDelayedEvent":
        return cls(order_id=e["order_id"], delay_days=e["delay_days"], reason=e["reason"],
                   source=e["source"], occurred_at=e["occurred_at"], sequence=e["sequence"])


Handler = Callable[[OrderDelayedEvent], None]


class EventBus:
    def __init__(self):
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        self._subs[event_type].append(handler)

    def publish(self, event: OrderDelayedEvent) -> None:
        for handler in self._subs[event.type]:
            handler(event)


bus = EventBus()


class OutboxListener:
    """Polls the integration layer's event API and publishes new events to the bus."""

    def __init__(self, event_bus: EventBus = bus):
        self.bus = event_bus
        self.cursor = 0
        self._stop = threading.Event()

    def poll_once(self) -> list[OrderDelayedEvent]:
        from tools import api_client
        raw = api_client.get("/api/v1/events", after=self.cursor)["events"]
        events = [OrderDelayedEvent.from_api(e) for e in raw if e["type"] == ORDER_DELAYED]
        for e in raw:
            self.cursor = max(self.cursor, e["sequence"])
        for evt in events:
            self.bus.publish(evt)
        return events

    def run_forever(self, interval: float = 2.0) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # keep the listener alive on transient errors
                print(f"[listener] poll failed: {exc}")
            self._stop.wait(interval)

    def stop(self) -> None:
        self._stop.set()


def simulate_erp_delay(order_id: str, delay_days: int, reason: str = "Carrier reported delay") -> dict:
    """What a carrier/TMS update looks like from the ERP's side.
    Writes straight to the ERP (it's the system of record producing the event)."""
    from integration.erp_client import erp
    r = erp().post(f"/erp/shipments/{order_id}/delay", json={"DELAY_D": delay_days, "RSN": reason})
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Simulate the ERP publishing ORDER_DELAYED")
    p.add_argument("--order", default="1842")
    p.add_argument("--days", type=int, default=4)
    p.add_argument("--reason", default="Port congestion at Felixstowe")
    a = p.parse_args()
    print(simulate_erp_delay(a.order, a.days, a.reason))

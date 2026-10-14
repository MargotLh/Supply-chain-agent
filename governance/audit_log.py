"""Append-only audit trail: every tool call, decision, approval and denial."""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import settings


@dataclass
class AuditEntry:
    actor: str            # e.g. "Inventory Agent", "human:ops.manager"
    event: str            # TOOL_CALL, TOOL_RESULT, TOOL_DENIED, DECISION, APPROVAL_*, ...
    summary: str
    correlation_id: str | None = None
    data: dict = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def line(self) -> str:
        t = datetime.fromisoformat(self.ts).astimezone().strftime("%H:%M:%S")
        return f"{t}  {self.actor:<18} {self.summary}"


class AuditLog:
    def __init__(self, path: str | None = settings.AUDIT_LOG_PATH):
        self.path = Path(path) if path else None
        self.entries: list[AuditEntry] = []
        self._listeners: list[Callable[[AuditEntry], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, fn: Callable[[AuditEntry], None]) -> None:
        self._listeners.append(fn)

    def record(self, actor: str, event: str, summary: str,
               correlation_id: str | None = None, **data) -> AuditEntry:
        entry = AuditEntry(actor, event, summary, correlation_id, data)
        with self._lock:
            self.entries.append(entry)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a") as f:
                    f.write(json.dumps(asdict(entry), default=str) + "\n")
        for fn in self._listeners:
            fn(entry)
        return entry

    def for_run(self, correlation_id: str) -> list[AuditEntry]:
        return [e for e in self.entries if e.correlation_id == correlation_id]


audit = AuditLog()

"""Where finished ScanRecords go. In-memory only for now; durable sinks come with POC-06
and must pass records through the storage policy first."""

from collections import deque
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from foodvision.measurement.events import ScanRecord


class EventSink(Protocol):
    def emit(self, record: "ScanRecord") -> None: ...


class InMemorySink:
    def __init__(self, maxlen: int = 1000) -> None:
        self.records: deque[ScanRecord] = deque(maxlen=maxlen)

    def emit(self, record: "ScanRecord") -> None:
        self.records.append(record)

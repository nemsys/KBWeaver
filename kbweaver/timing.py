"""Lightweight timing utilities for observability.

Every subsystem boundary emits wall-clock timing data per SAD §7.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator


@dataclass
class TimingRecord:
    """Accumulated timing measurements for a single pipeline run."""

    stages: dict[str, float] = field(default_factory=dict)

    def record(self, stage: str, seconds: float) -> None:
        self.stages[stage] = seconds

    @property
    def total(self) -> float:
        return sum(self.stages.values())

    def format_report(self) -> str:
        """Return a human-readable multi-line timing report."""
        lines: list[str] = []
        for stage, secs in self.stages.items():
            lines.append(f"  {stage + ':':<25s} {secs:.1f}s")
        lines.append(f"  {'Total:':<25s} {self.total:.1f}s")
        return "\n".join(lines)


@contextmanager
def timed(record: TimingRecord, stage: str) -> Generator[None, None, None]:
    """Context manager that records wall-clock time for *stage* into *record*.

    Usage::

        rec = TimingRecord()
        with timed(rec, "parse"):
            do_parsing()
        print(rec.stages["parse"])  # elapsed seconds
    """
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        record.record(stage, elapsed)

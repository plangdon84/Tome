"""Token and cost accounting for every LLM call."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("tome.llm")
DEFAULT_LOG = Path(os.environ.get("TOME_USAGE_LOG", "data/llm-usage.jsonl"))


@dataclass
class UsageRecord:
    ts: str
    provider: str
    model: str
    series: str
    purpose: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float | None
    latency_s: float
    ok: bool
    error: str | None = None


@dataclass
class UsageLog:
    """Appends one JSON line per call and keeps running totals in memory."""

    path: Path | None = DEFAULT_LOG
    records: list[UsageRecord] = field(default_factory=list)

    def add(self, record: UsageRecord) -> None:
        self.records.append(record)
        log.info(
            "llm %s/%s series=%s purpose=%s tokens=%d+%d cost=%s %.2fs%s",
            record.provider,
            record.model,
            record.series,
            record.purpose,
            record.prompt_tokens,
            record.completion_tokens,
            record.cost_usd,
            record.latency_s,
            "" if record.ok else f" ERROR {record.error}",
        )
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(record)) + "\n")

    @property
    def prompt_tokens(self) -> int:
        return sum(r.prompt_tokens for r in self.records)

    @property
    def completion_tokens(self) -> int:
        return sum(r.completion_tokens for r in self.records)

    @property
    def cost_usd(self) -> float:
        return sum(r.cost_usd or 0.0 for r in self.records)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")

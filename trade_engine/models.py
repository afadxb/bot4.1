"""Core dataclasses used across the intraday engine."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


class Side(str, Enum):
    LONG = "long"
    SHORT = "short"


@dataclass(slots=True)
class Bar:
    symbol: str
    timeframe: str
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class Signal:
    """Standardised representation of a ranked trade opportunity."""

    symbol: str
    run_ts: datetime
    cycle_id: str
    entry_hint: float | None
    stop_hint: float | None
    base_score: float
    ai_adj_score: float
    final_score: float
    reasons: tuple[str, ...]
    rules_passed: Mapping[str, bool]
    features: Mapping[str, Any]
    rank: int | None = None

    def with_scores(self, *, ai_adj_score: float | None = None, final_score: float | None = None) -> "Signal":
        """Return a copy of the signal with updated score fields."""

        payload = {}
        if ai_adj_score is not None:
            payload["ai_adj_score"] = ai_adj_score
        if final_score is not None:
            payload["final_score"] = final_score
        return replace(self, **payload)


@dataclass(slots=True)
class PlannedOrder:
    """Position plan produced by risk-aware sizing."""

    symbol: str
    side: str
    qty: int
    entry: float
    stop: float
    scale_out: float
    target: float
    trail_mode: str
    risk_context: Mapping[str, Any]


@dataclass(slots=True)
class TradeIntent:
    symbol: str
    side: Side
    confidence: float
    quantity: float
    entry: float
    stop: float
    target: float
    metadata: Mapping[str, float]


@dataclass(slots=True)
class Position:
    symbol: str
    side: Side
    quantity: float
    entry_price: float
    mark: float
    unrealized_pnl: float


@dataclass(slots=True)
class AIOverlay:
    symbol: str
    ts: datetime
    sentiment: float
    regime: str
    approved: bool
    metadata: Mapping[str, float]


@dataclass(slots=True)
class RiskEvent:
    """Structured risk telemetry persisted for auditing."""

    ts: datetime
    session: str
    type: str
    symbol: str | None = None
    value: float | None = None
    meta_json: Mapping[str, Any] = field(default_factory=dict)

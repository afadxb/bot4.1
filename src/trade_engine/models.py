"""Core dataclasses used across the intraday engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Mapping


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
    symbol: str
    ts: datetime
    signal_type: str
    score: float
    strength: float
    metadata: Mapping[str, float]


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

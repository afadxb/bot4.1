"""Configuration models for the intraday trading engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Sequence


@dataclass(slots=True)
class RiskConfig:
    """Risk parameters used by :class:`trade_engine.risk.manager.RiskManager`.

    Attributes
    ----------
    max_position_per_symbol:
        Maximum number of concurrent open positions per symbol.
    max_total_positions:
        Total simultaneous positions allowed across the portfolio.
    max_notional:
        Hard cap on gross exposure in account currency.
    max_drawdown:
        Intraday drawdown (in account currency) that forces flattening.
    per_trade_risk:
        Maximum loss tolerated per trade.
    halted_symbols:
        Symbols that should be skipped from trading (news halts, compliance, etc.).
    """

    max_position_per_symbol: int = 1
    max_total_positions: int = 5
    max_notional: float = 100_000.0
    max_drawdown: float = 5_000.0
    per_trade_risk: float = 500.0
    halted_symbols: Sequence[str] = field(default_factory=tuple)


@dataclass(slots=True)
class CycleConfig:
    """Settings that control the scheduling cadence for the orchestrator."""

    interval_seconds: int = 300
    market_open: time = time(9, 30)
    market_close: time = time(16, 0)
    flatten_buffer_minutes: int = 10


@dataclass(slots=True)
class AIConfig:
    """Feature flags for optional AI overlays."""

    enabled: bool = False
    require_positive_sentiment: bool = False
    require_favorable_regime: bool = False


@dataclass(slots=True)
class EngineConfig:
    """Top level configuration passed to the runtime orchestrator."""

    database_path: str = "trade_engine.db"
    top_n: int = 20
    cycle: CycleConfig = field(default_factory=CycleConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    dry_run: bool = True

    def with_overrides(self, **kwargs: object) -> "EngineConfig":
        """Return a copy of the configuration with selected fields replaced."""

        data = {
            "database_path": self.database_path,
            "top_n": self.top_n,
            "cycle": self.cycle,
            "risk": self.risk,
            "ai": self.ai,
            "dry_run": self.dry_run,
        }
        data.update(kwargs)
        return EngineConfig(**data)

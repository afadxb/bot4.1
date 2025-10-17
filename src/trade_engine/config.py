"""Configuration models for the intraday trading engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Literal


@dataclass(slots=True)
class OrchestratorConfig:
    """Scheduling and session controls for the orchestrator."""

    timezone: str = "America/Toronto"
    cadence_min: int = 5
    intraday_top_n: int = 20
    flatten_time_et: str = "15:55"
    drawdown_halt_pct: float = 10.0
    start_with_dry_run: bool = True
    flatten_time: time = field(init=False)

    def __post_init__(self) -> None:
        try:
            hour, minute = [int(part) for part in self.flatten_time_et.split(":", 1)]
        except ValueError as exc:  # pragma: no cover - defensive guard
            raise ValueError("flatten_time_et must be HH:MM") from exc
        object.__setattr__(self, "flatten_time", time(hour, minute))


@dataclass(slots=True)
class RiskConfig:
    """Risk controls applied by :class:`trade_engine.risk.manager.RiskManager`."""

    enable_limits: bool = True
    risk_per_trade_pct: float = 1.0
    daily_trade_cap: int = 20
    daily_drawdown_halt_pct: float = 10.0
    min_tick_buffer: float = 0.01
    max_position_value_pct: float = 20.0
    max_portfolio_exposure_pct: float = 100.0
    earnings_blackout: bool = True
    earnings_blackout_mode: Literal["cap", "veto"] = "cap"
    spread_penalty_bp: int = 50
    illiquidity_veto: bool = True
    account_equity: float = 100_000.0


@dataclass(slots=True)
class ExecutionConfig:
    enable_orders: bool = False
    scale_out_at_r_multiple: float = 1.0
    final_target_r_multiple: float = 2.0
    trail_mode: Literal["ema21", "atr", "none"] = "ema21"
    atr_trail_mult: float = 2.0


@dataclass(slots=True)
class SupertrendConfig:
    atr_period: int = 10
    atr_mult: float = 3


@dataclass(slots=True)
class StrategyConfig:
    ema_fast: int = 9
    ema_slow: int = 21
    ema_bias: int = 50
    vwap_required: bool = True
    vol_spike_multiple: float = 1.5
    consolidation_lookback: int = 20
    catalyst_required: bool = True
    enable_supertrend: bool = False
    supertrend: SupertrendConfig = field(default_factory=SupertrendConfig)


@dataclass(slots=True)
class FinbertConfig:
    enable: bool = False
    min_headlines: int = 1
    decay_hours: int = 12


@dataclass(slots=True)
class AIConfig:
    enable_gating: bool = False
    require_positive_sentiment: bool = False
    require_favorable_regime: bool = False
    finbert: FinbertConfig = field(default_factory=FinbertConfig)


@dataclass(slots=True)
class FeedConfig:
    enable: bool = False


@dataclass(slots=True)
class IBKRFeedConfig(FeedConfig):
    throttle_rps: int = 2


@dataclass(slots=True)
class FeedsConfig:
    ibkr: IBKRFeedConfig = field(default_factory=IBKRFeedConfig)
    finnhub: FeedConfig = field(default_factory=FeedConfig)
    yahoo_rss: FeedConfig = field(default_factory=lambda: FeedConfig(enable=True))


@dataclass(slots=True)
class EngineConfig:
    """Top level configuration passed to the runtime orchestrator."""

    database_path: str = "trade_engine.db"
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    feeds: FeedsConfig = field(default_factory=FeedsConfig)

    def with_overrides(self, **kwargs: object) -> "EngineConfig":
        """Return a copy of the configuration with selected fields replaced."""

        data = {
            "database_path": self.database_path,
            "orchestrator": self.orchestrator,
            "risk": self.risk,
            "execution": self.execution,
            "strategy": self.strategy,
            "ai": self.ai,
            "feeds": self.feeds,
        }
        data.update(kwargs)
        return EngineConfig(**data)

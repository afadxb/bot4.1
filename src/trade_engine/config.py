"""Configuration models and loaders for the intraday trading engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import time
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

import yaml


def _deep_update(target: MutableMapping[str, Any], updates: Mapping[str, Any]) -> MutableMapping[str, Any]:
    """Recursively merge ``updates`` into ``target``."""

    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), MutableMapping):
            _deep_update(target[key], value)  # type: ignore[index]
        else:
            target[key] = value
    return target


def _parse_time(value: str | time) -> time:
    if isinstance(value, time):
        return value
    hours, minutes = (int(part) for part in value.split(":"))
    return time(hour=hours, minute=minutes)


@dataclass(slots=True)
class OrchestratorConfig:
    timezone: str = "America/Toronto"
    cadence_min: int = 5
    intraday_top_n: int = 20
    flatten_time_et: time = time(15, 55)
    drawdown_halt_pct: float = 10.0
    start_with_dry_run: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "OrchestratorConfig":
        payload = dict(data)
        if "flatten_time_et" in payload:
            payload["flatten_time_et"] = _parse_time(payload["flatten_time_et"])
        return cls(**payload)


@dataclass(slots=True)
class RiskConfig:
    enable_limits: bool = True
    risk_per_trade_pct: float = 1.0
    daily_trade_cap: int = 20
    daily_drawdown_halt_pct: float = 10.0
    min_tick_buffer: float = 0.01
    max_position_value_pct: float = 20.0
    max_portfolio_exposure_pct: float = 100.0
    earnings_blackout: bool = True
    earnings_blackout_mode: str = "cap"
    spread_penalty_bp: int = 50
    illiquidity_veto: bool = True
    # Compatibility attributes used by existing subsystems
    max_position_per_symbol: int = 1
    max_total_positions: int = 5
    max_notional: float = 100_000.0
    max_drawdown: float = 5_000.0
    per_trade_risk: float = 500.0
    halted_symbols: Sequence[str] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RiskConfig":
        return cls(**dict(data))


@dataclass(slots=True)
class ExecutionConfig:
    enable_orders: bool = False
    scale_out_at_r_multiple: float = 1.0
    final_target_r_multiple: float = 2.0
    trail_mode: str = "ema21"
    atr_trail_mult: float = 2.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ExecutionConfig":
        return cls(**dict(data))


@dataclass(slots=True)
class SupertrendConfig:
    atr_period: int = 10
    atr_mult: float = 3.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SupertrendConfig":
        return cls(**dict(data))


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

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "StrategyConfig":
        payload = dict(data)
        if "supertrend" in payload:
            payload["supertrend"] = SupertrendConfig.from_mapping(payload["supertrend"])
        return cls(**payload)


@dataclass(slots=True)
class FinbertConfig:
    enable: bool = False
    min_headlines: int = 1
    decay_hours: int = 12

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FinbertConfig":
        return cls(**dict(data))


@dataclass(slots=True)
class AIConfig:
    enable_gating: bool = False
    finbert: FinbertConfig = field(default_factory=FinbertConfig)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AIConfig":
        payload = dict(data)
        if "finbert" in payload:
            payload["finbert"] = FinbertConfig.from_mapping(payload["finbert"])
        return cls(**payload)


@dataclass(slots=True)
class FeedToggleConfig:
    enable: bool = False
    throttle_rps: int | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FeedToggleConfig":
        return cls(**dict(data))


@dataclass(slots=True)
class FeedsConfig:
    ibkr: FeedToggleConfig = field(default_factory=lambda: FeedToggleConfig(enable=False, throttle_rps=2))
    finnhub: FeedToggleConfig = field(default_factory=FeedToggleConfig)
    yahoo_rss: FeedToggleConfig = field(default_factory=lambda: FeedToggleConfig(enable=True))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FeedsConfig":
        payload = dict(data)
        if "ibkr" in payload:
            payload["ibkr"] = FeedToggleConfig.from_mapping(payload["ibkr"])
        if "finnhub" in payload:
            payload["finnhub"] = FeedToggleConfig.from_mapping(payload["finnhub"])
        if "yahoo_rss" in payload:
            payload["yahoo_rss"] = FeedToggleConfig.from_mapping(payload["yahoo_rss"])
        return cls(**payload)


@dataclass(slots=True)
class EngineConfig:
    database_path: str = "trade_engine.db"
    orchestrator: OrchestratorConfig = field(default_factory=OrchestratorConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    feeds: FeedsConfig = field(default_factory=FeedsConfig)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None = None) -> "EngineConfig":
        if not data:
            return cls()
        base = asdict(cls())
        merged = _deep_update(base, data)
        return cls(
            database_path=merged.get("database_path", "trade_engine.db"),
            orchestrator=OrchestratorConfig.from_mapping(merged.get("orchestrator", {})),
            risk=RiskConfig.from_mapping(merged.get("risk", {})),
            execution=ExecutionConfig.from_mapping(merged.get("execution", {})),
            strategy=StrategyConfig.from_mapping(merged.get("strategy", {})),
            ai=AIConfig.from_mapping(merged.get("ai", {})),
            feeds=FeedsConfig.from_mapping(merged.get("feeds", {})),
        )

    @property
    def dry_run(self) -> bool:
        return not self.execution.enable_orders

    @property
    def top_n(self) -> int:
        return self.orchestrator.intraday_top_n

    def merge(self, data: Mapping[str, Any]) -> "EngineConfig":
        base = asdict(self)
        merged = _deep_update(base, data)
        return EngineConfig.from_dict(merged)


def _load_env_file(env_path: Path) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key_parts = key.lower().split("__")
        current = overrides
        for part in key_parts[:-1]:
            current = current.setdefault(part, {})  # type: ignore[assignment]
        current[key_parts[-1]] = yaml.safe_load(raw_value)
    return overrides


def load_engine_config(yaml_path: str | Path | None = None, env_path: str | Path | None = None) -> EngineConfig:
    """Load configuration from YAML and optional ``.env`` overrides."""

    config_payload: dict[str, Any] = {}
    if yaml_path:
        yaml_file = Path(yaml_path)
        if yaml_file.exists():
            loaded = yaml.safe_load(yaml_file.read_text()) or {}
            if not isinstance(loaded, Mapping):
                raise ValueError("Configuration root must be a mapping")
            config_payload = dict(loaded)
    if env_path:
        env_file = Path(env_path)
        if env_file.exists():
            env_overrides = _load_env_file(env_file)
            config_payload = dict(_deep_update(config_payload, env_overrides))
    return EngineConfig.from_dict(config_payload)


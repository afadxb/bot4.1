# Intraday Trading Engine

This repository contains a reference intraday trading engine that extends a Phase‑1
watchlist into a complete intraday workflow.  The stack assumes SQLite as the shared
store, Interactive Brokers (IBKR) as the primary data and execution venue, and exposes
optional AI overlays to gate trades.

## Architecture Overview

The runtime is decomposed into the following layers:

1. **Scheduler / Orchestrator** – coordinates the intraday cadence (5/15 minute cycles).
2. **Data Layer** – fetches bars and catalyst data (IBKR, news feeds) with caching hooks.
3. **Feature & AI Layer** – computes technical indicators and optional sentiment/regime
   screens.
4. **Strategy Engine** – evaluates deterministic rules, scores symbols, and produces
   trade intents.
5. **Execution Layer** – sizes orders, routes them to IBKR (stubbed by default), and
   journals activity.
6. **Persistence** – manages SQLite migrations and helper queries for dashboards.
7. **Observability** – records signals, AI overlays, risk events, and trades for Streamlit
   dashboards and analytics.

All feature groups are flag‑gated via `EngineConfig`, enabling selective rollout of AI
components or live execution.

## Quickstart

1. Populate the Phase‑1 watchlist:

   ```bash
   python -m trade_engine.tools.seed_watchlist --database trade_engine.db symbols.txt
   ```

   (You can also upsert rows manually using the `Database` helper.)

2. Run a single cycle in dry‑run mode:

   ```bash
   python -m trade_engine.main --database trade_engine.db --top-n 20 --cadence-min 5 --once
   ```

3. Inspect the generated artefacts via Streamlit or offline JSON exports:

   ```bash
   python -m trade_engine.tools.export --database trade_engine.db --out cycle.json
   ```

## Development Notes

* Real IBKR connectivity can be plugged in by swapping the stub `IBKRClient` and
  enabling `--live` in the CLI.  The orchestrator honours the configured market
  timezone, five-minute cadence, and flatten guard (15:55 ET by default) while
  continuously looping.
* AI gating is optional and can be toggled with `--enable-ai`.  Sentiment/regime models
  are deterministic placeholders ready to be replaced by upstream services.
* The SQLite schema is migration friendly and can be extended with additional signals or
  analytics tables as new strategies are introduced.

## Configuration

Runtime configuration is loaded via `EngineConfig` and mirrors a YAML‑friendly structure:

```yaml
orchestrator:
  timezone: America/Toronto
  cadence_min: 5
  intraday_top_n: 20
  flatten_time_et: "15:55"
  drawdown_halt_pct: 10
  start_with_dry_run: true

risk:
  enable_limits: true
  risk_per_trade_pct: 1.0
  daily_trade_cap: 20
  daily_drawdown_halt_pct: 10.0
  min_tick_buffer: 0.01
  max_position_value_pct: 20.0
  max_portfolio_exposure_pct: 100
  earnings_blackout: true
  earnings_blackout_mode: cap
  spread_penalty_bp: 50
  illiquidity_veto: true

execution:
  enable_orders: false
  scale_out_at_r_multiple: 1.0
  final_target_r_multiple: 2.0
  trail_mode: ema21
  atr_trail_mult: 2.0

strategy:
  ema_fast: 9
  ema_slow: 21
  ema_bias: 50
  vwap_required: true
  vol_spike_multiple: 1.5
  consolidation_lookback: 20
  catalyst_required: true
  enable_supertrend: false
  supertrend:
    atr_period: 10
    atr_mult: 3

ai:
  enable_gating: false
  finbert:
    enable: false
    min_headlines: 1
    decay_hours: 12

feeds:
  ibkr:
    enable: false
    throttle_rps: 2
  finnhub:
    enable: false
  yahoo_rss:
    enable: true
```

Environment overrides (e.g. API keys) should be provided via a `.env` file loaded prior
to process start.  All keys are additive; omitting a block falls back to the defaults
above, preserving the EMA‑only, AI‑off, dry‑run behaviour.

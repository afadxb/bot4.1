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
   python -m trade_engine.main --database trade_engine.db --top-n 20 --interval 300
   ```

3. Inspect the generated artefacts via Streamlit or offline JSON exports:

   ```bash
   python -m trade_engine.tools.export --database trade_engine.db --out cycle.json
   ```

## Development Notes

* Real IBKR connectivity can be plugged in by swapping the stub `IBKRClient` and
  enabling `--live` in the CLI. Sample CLI commands and parameters are documented in
  [`.env.example`](.env.example) for quick reference.
* AI gating is optional and can be toggled with `--enable-ai`.  Sentiment/regime models
  are deterministic placeholders ready to be replaced by upstream services.
* The SQLite schema is migration friendly and can be extended with additional signals or
  analytics tables as new strategies are introduced.
* Operational expectations for dashboards, observability, rollout, and testing are
  documented in [`docs/phase2_operational_spec.md`](docs/phase2_operational_spec.md).

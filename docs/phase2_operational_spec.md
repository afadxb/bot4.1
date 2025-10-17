# Phase 2 Operational Playbook

This document captures the operational guardrails and rollout guidelines for the Phase 2 intraday engine. The goal is to maintain the Phase 1 behaviour by default while introducing richer observability, risk handling, and deployment practices that can be toggled on as confidence grows.

## 8. Dashboard & Observability

### Streamlit dashboards
The dashboard should surface real-time visibility into the trading loop through four primary panels:

1. **Signals tape** – display each symbol with its composite score, supporting reasons, AI score delta, and pass/fail state for guardrail rules.
2. **Risk panel** – summarise recent risk events (capital limits, drawdowns, exposure changes), current portfolio exposure percentage, and an intraday equity curve.
3. **Trades & positions** – outline sizing context, open R multiples, and trail state for live positions.
4. **AI lift** – when historical data is available, chart the change in win rate with AI gating enabled versus disabled.

### Logging expectations
* **INFO** logs capture lifecycle milestones, guardrail decisions, and order intents/results.
* **DEBUG** logs expand on sizing math, intermediate indicator values, AI provenance, and guardrail penalty details.

### Optional alerts
Integrate Pushover notifications to flag fills, halts, or error conditions when alerting is enabled.

## 9. Failure & Resilience
* Non-critical data gaps should fail open (for example, missing spread data should not trigger a penalty).
* Unknown equity or exposure metrics must force a fail-safe: raise warnings and skip new entries.
* Implement retries with backoff inside data adapters and reuse cached reads on transient failures.
* Keep migrations idempotent and ensure storage helpers safely tolerate re-runs.

## 10. Testing Strategy
* **Unit tests** cover indicators, sizing calculations, guardrails, and AI adjustments.
* **Integration tests** exercise an intraday cycle with simulated feeds and no external network dependency.
* **Non-regression suites** compare the Phase 1 CLI outputs against golden files.
* Target at least 90% coverage on any module that is modified.

Representative scenarios to encode in tests:
1. Trade cap reached – the third signal is skipped and a risk event is logged.
2. Drawdown breach – new entries halt while exits continue to be permitted.
3. Exposure cap rejection – the system logs the event and avoids sending the order.
4. Earnings blackout (cap versus veto) – scores are clamped or zeroed based on configuration.
5. Supertrend toggled off/on – behaviour remains unchanged when gating is disabled.
6. Flatten guard executes even after a trading halt.

## 11. Deployment & Operations
* Provide `.env` templates to map IBKR and Finnhub credentials along with a dashboard toggle.
* Use cron or a systemd timer to launch the process, and leverage APScheduler inside the service for cadence control.
* Emit heartbeat logs and plan for optional Prometheus endpoints to support future health checks.

## 12. Security & Access
* Load secrets exclusively from environment variables or the operating system’s secret store—never commit credentials.
* Scope API keys with least privilege and default to IBKR paper trading during rollout.
* Mask tokens in logs and redact sensitive URLs when errors are emitted.

## 13. Performance Considerations
* Cache bar data by `(symbol, timeframe, timestamp)` with sensible TTL and retention limits.
* Apply request throttling for IBKR by configuring allowable requests per second.
* Vectorise feature computations wherever batching is possible.
* Defer AI scoring to shortlisted symbols to conserve CPU resources.

## 14. Rollout Plan
1. Apply database migrations and configuration with new feature flags disabled.
2. Run the intraday cycle in dry-run mode and validate `signals` plus `risk_events` outputs.
3. Enable `feeds.ibkr.enable=true` to consume live bars from IBKR.
4. Activate AI gating and Supertrend after baseline metrics are established.

## 15. Acceptance Criteria
* Default configuration keeps Phase 1 behaviour unchanged.
* Each intraday cycle persists signals and risk_events rows.
* Risk caps and halts are deterministic and observable.
* TradeManager honours sizing rules and exposure checks.
* End-of-day flattening executes reliably.
* Test suites pass with ≥90% coverage on touched modules.

## 16. Extension Backlog (Post Phase 2)
* Develop predictive success modelling (meta-labelling).
* Introduce regime detection using VIX or breadth gating.
* Expand to multi-venue adapters (e.g., Kraken/CCXT) through a common interface.
* Push real-time dashboard updates via WebSockets.
* Add Prometheus metrics feeding a Grafana dashboard.

## 17. Implementation Sequencing
Plan the rollout as a sequence of small, auditable commits:

1. Migrations, storage helpers, and database views.
2. Configuration keys and environment mapping (defaulting to no behavioural changes).
3. DataHub adapters plus caching logic.
4. Feature and strategy updates, keeping Supertrend behind a flag.
5. Risk guardrails spanning orchestrator and scorer flows.
6. TradeManager sizing, targets, and trails (respecting dry-run).
7. Dashboard iterations and alerting hooks.
8. Tests, golden files, and accompanying documentation updates.

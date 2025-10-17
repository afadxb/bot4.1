-- Phase 2 additive schema for analytics and AI provenance
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    run_ts DATETIME NOT NULL,
    features_json TEXT NOT NULL,
    rules_passed_json TEXT NOT NULL,
    base_score REAL NOT NULL,
    ai_adj_score REAL NOT NULL,
    final_score REAL NOT NULL,
    rank INTEGER,
    reasons_text TEXT,
    cycle_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_provenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    run_ts DATETIME NOT NULL,
    source TEXT NOT NULL,
    sentiment_score REAL NOT NULL,
    sentiment_label TEXT NOT NULL,
    meta_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bars_cache (
    symbol TEXT NOT NULL,
    tf TEXT NOT NULL,
    ts DATETIME NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY(symbol, tf, ts)
);

CREATE TABLE IF NOT EXISTS risk_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts DATETIME DEFAULT CURRENT_TIMESTAMP,
    session TEXT,
    type TEXT NOT NULL,
    symbol TEXT,
    value REAL,
    meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS metrics_equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts DATETIME DEFAULT CURRENT_TIMESTAMP,
    session TEXT,
    starting_equity REAL NOT NULL,
    realized_pnl REAL NOT NULL,
    unrealized_pnl REAL NOT NULL
);

CREATE VIEW IF NOT EXISTS v_latest_signals AS
SELECT s.*
FROM signals s
JOIN (
    SELECT symbol, MAX(run_ts) AS run_ts
    FROM signals
    GROUP BY symbol
) latest ON latest.symbol = s.symbol AND latest.run_ts = s.run_ts;

CREATE VIEW IF NOT EXISTS v_risk_events_today AS
SELECT * FROM risk_events
WHERE DATE(ts) = DATE('now', 'localtime');

CREATE VIEW IF NOT EXISTS v_intraday_exposure AS
SELECT symbol, SUM(value) AS gross_exposure
FROM risk_events
WHERE type = 'exposure'
GROUP BY symbol;

CREATE VIEW IF NOT EXISTS v_daily_equity AS
SELECT
    ts,
    session,
    starting_equity,
    realized_pnl,
    unrealized_pnl,
    CASE
        WHEN starting_equity = 0 THEN 0
        ELSE (realized_pnl + unrealized_pnl) / starting_equity * 100
    END AS drawdown_pct,
    CASE
        WHEN starting_equity = 0 THEN 0
        ELSE (realized_pnl + unrealized_pnl) <= -starting_equity * 0.1
    END AS halt_flag
FROM metrics_equity;

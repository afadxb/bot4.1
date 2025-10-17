"""Simple helper to seed the watchlist table."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..db import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the watchlist table")
    parser.add_argument("--database", default="trade_engine.db", help="SQLite database path")
    parser.add_argument("file", help="Text file with one symbol per line")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database = Database(args.database)
    entries: list[tuple[str, str | None, str | None]] = []
    for line in Path(args.file).read_text().splitlines():
        symbol = line.strip().upper()
        if not symbol or symbol.startswith("#"):
            continue
        entries.append((symbol, None, None))
    database.upsert_watchlist(entries)
    print(f"Seeded {len(entries)} watchlist symbols")


if __name__ == "__main__":
    main()

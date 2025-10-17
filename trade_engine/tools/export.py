"""Export journal data for offline dashboard usage."""

from __future__ import annotations

import argparse

from ..dashboard.layouts import export_json
from ..db import Database


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export latest signals and trades")
    parser.add_argument("--database", default="trade_engine.db", help="SQLite database path")
    parser.add_argument("--out", default="export.json", help="Output JSON file")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database = Database(args.database)
    export_json(database, args.out)
    print(f"Exported data to {args.out}")


if __name__ == "__main__":
    main()

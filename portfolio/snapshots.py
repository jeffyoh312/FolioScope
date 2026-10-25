"""Optional local SQLite store for timestamped portfolio-value snapshots."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def save_snapshot(
    db_path: str | Path, value: float, label: str, timestamp: str | None = None
) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    recorded_at = timestamp or datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS snapshots ("
            "recorded_at TEXT NOT NULL PRIMARY KEY, value_usd REAL NOT NULL, "
            "source TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT OR REPLACE INTO snapshots (recorded_at, value_usd, source) VALUES (?, ?, ?)",
            (recorded_at, float(value), label),
        )


def read_snapshots(db_path: str | Path) -> pd.DataFrame:
    if not Path(db_path).exists():
        return pd.DataFrame(columns=["recorded_at", "value_usd", "source"])
    with sqlite3.connect(db_path) as connection:
        return pd.read_sql_query(
            "SELECT * FROM snapshots ORDER BY recorded_at", connection
        )

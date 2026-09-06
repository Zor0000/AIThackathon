"""Idempotently copy VeriSure records from SQLite into Supabase Postgres."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from verisure.storage import CaseStore

TABLES = (
    "cases",
    "audit_events",
    "messages",
    "questionnaire_sessions",
    "questionnaire_answers",
)
TABLES_WITH_SEQUENCE = ("audit_events", "messages", "questionnaire_answers")


def main() -> None:
    source_path = Path(os.getenv("LEGACY_SQLITE_PATH", "data/verisure.db"))
    target = CaseStore.from_environment()
    if not target.uses_postgres:
        raise RuntimeError("SUPABASE_DB_URL must contain a PostgreSQL connection URL.")
    if not source_path.exists():
        raise FileNotFoundError(f"SQLite source database was not found: {source_path}")

    with sqlite3.connect(source_path) as source:
        source.row_factory = sqlite3.Row
        available = {
            row["name"]
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        copied: dict[str, int] = {}
        with target._connection() as destination:
            for table in TABLES:
                if table not in available:
                    copied[table] = 0
                    continue
                rows = source.execute(f"SELECT * FROM {table}").fetchall()
                if not rows:
                    copied[table] = 0
                    continue
                columns = tuple(rows[0].keys())
                names = ", ".join(columns)
                placeholders = ", ".join("?" for _ in columns)
                statement = (
                    f"INSERT INTO {table} ({names}) VALUES ({placeholders}) "
                    "ON CONFLICT DO NOTHING"
                )
                inserted = 0
                for row in rows:
                    values = tuple(
                        bool(row[column])
                        if column in {"consent_confirmed", "is_valid"}
                        else row[column]
                        for column in columns
                    )
                    cursor = destination.execute(statement, values)
                    inserted += max(cursor.rowcount, 0)
                copied[table] = inserted

            for table in TABLES_WITH_SEQUENCE:
                destination.execute(
                    "SELECT setval(pg_get_serial_sequence(?, 'id'), "
                    "COALESCE((SELECT MAX(id) FROM " + table + "), 1), true)",
                    (table,),
                )

    print("Migration completed.")
    for table in TABLES:
        print(f"{table}: {copied[table]} row(s) inserted")


if __name__ == "__main__":
    main()

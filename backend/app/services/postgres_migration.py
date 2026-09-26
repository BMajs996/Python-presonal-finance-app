"""Copy a consistent SQLite snapshot into an empty PostgreSQL schema."""

import hashlib
import json
import sqlite3
import tempfile
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg import sql

from ..database import FinanceDatabase
from ..migrations import LATEST_SCHEMA_VERSION
from ..postgres_connection import WRITE_LOCK, record_factory
from ..postgres_database import TABLES, create_schema, install_guards
from .backup_service import BackupService


def _normalized(value):
    if isinstance(value, (float, Decimal)):
        return Decimal(str(value))
    return value


def transfer_sqlite(source_path: Path, target_url: str, currency: str, *, commit: bool = False):
    source_path = source_path.expanduser().resolve()
    if not source_path.is_file():
        raise ValueError("SQLite source does not exist")
    reservation = sqlite3.connect(source_path.as_uri() + "?mode=rw", uri=True, timeout=5)
    try:
        # Keep the backup and copied snapshot consistent, even if another writer is running.
        reservation.execute("BEGIN IMMEDIATE")
        return _transfer_locked(source_path, target_url, currency, commit=commit)
    finally:
        reservation.rollback()
        reservation.close()


def _transfer_locked(source_path: Path, target_url: str, currency: str, *, commit: bool):
    backup_service = BackupService(source_path)
    backup = backup_service.create_backup(prefix="pre-postgres") if commit else None
    with tempfile.TemporaryDirectory(prefix="finance-transfer-") as directory:
        snapshot = Path(directory) / "snapshot.db"
        backup_service._snapshot_database(source_path, snapshot)
        source = FinanceDatabase(snapshot, currency)
        try:
            report = BackupService(snapshot).integrity_check()
            if not report.ok:
                raise ValueError("SQLite snapshot failed integrity verification")
            if report.schema_version != LATEST_SCHEMA_VERSION:
                raise ValueError("Unsupported SQLite schema version")
            names = {
                row[0]
                for row in source.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            if names != set(TABLES):
                raise ValueError("SQLite source has unsupported tables; nothing was copied")
            main = source.conn.execute("SELECT currency FROM accounts WHERE name='Main Account'").fetchone()
            if main is None or main[0] != currency:
                raise ValueError("Source currency does not match BASE_CURRENCY")
            with psycopg.connect(target_url, autocommit=True, row_factory=record_factory) as target:
                # DDL, rows, sequence reset, guards, and verification share one transaction.
                with target.transaction(force_rollback=not commit):
                    target.execute("SELECT pg_advisory_xact_lock(%s)", (WRITE_LOCK,))
                    if target.execute(
                        "SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() LIMIT 1"
                    ).fetchone():
                        raise ValueError("PostgreSQL destination schema must be empty")
                    create_schema(target)
                    counts = {}
                    digest = hashlib.sha256()
                    for table in TABLES:
                        columns = [row["name"] for row in source.conn.execute(f"PRAGMA table_info({table})")]
                        source_query = sql.SQL("SELECT * FROM {} ORDER BY {}").format(
                            sql.Identifier(table),
                            sql.SQL(", ").join(map(sql.Identifier, ["id"] if "id" in columns else columns)),
                        )
                        rows = source.conn.execute(source_query.as_string()).fetchall()
                        query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                            sql.Identifier(table),
                            sql.SQL(", ").join(map(sql.Identifier, columns)),
                            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                        )
                        with target.cursor() as cursor:
                            cursor.executemany(query, [tuple(row) for row in rows])
                        copied = target.execute(
                            sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
                                sql.SQL(", ").join(map(sql.Identifier, columns)),
                                sql.Identifier(table),
                                sql.SQL(", ").join(
                                    map(sql.Identifier, ["id"] if "id" in columns else columns)
                                ),
                            )
                        ).fetchall()
                        expected = [[_normalized(value) for value in row] for row in rows]
                        actual = [[_normalized(row[column]) for column in columns] for row in copied]
                        if expected != actual:
                            raise ValueError(f"Verification failed for {table}; transfer rolled back")
                        counts[table] = len(rows)
                        digest.update(json.dumps([table, expected], default=str, ensure_ascii=True).encode())
                        if "id" in columns:
                            sequence = source.conn.execute(
                                "SELECT seq FROM sqlite_sequence WHERE name=?", (table,)
                            ).fetchone()
                            highest = max((row["id"] for row in rows), default=0)
                            highest = max(highest, sequence[0] if sequence else 0)
                            target.execute(
                                "SELECT setval(pg_get_serial_sequence(%s,'id'),%s,%s)",
                                (table, max(highest, 1), highest > 0),
                            )
                    install_guards(target)
                    return {
                        "status": "ok",
                        "committed": commit,
                        "counts": counts,
                        "verified_sha256": digest.hexdigest(),
                        "source_backup": str(backup) if backup else None,
                    }
        finally:
            source.close()

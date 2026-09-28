import argparse
import json
import sqlite3
import sys
from pathlib import Path

import psycopg

from .core.config import settings
from .database import FinanceDatabase
from .database_factory import open_database
from .services.backup_service import BackupError, BackupService
from .services.future_entry_review import review_future_entries
from .services.postgres_migration import transfer_sqlite
from .services.recurring_runner import process_recurring


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finance Dashboard database recovery tools")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--database",
        type=Path,
        default=None,
        help="SQLite database path",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup", parents=[common], help="Create a verified backup archive")
    backup.add_argument(
        "destination",
        type=Path,
        nargs="?",
        help="Destination directory or .financebackup file",
    )

    commands.add_parser("integrity", parents=[common], help="Check SQLite and foreign-key integrity")
    commands.add_parser("process-recurring", parents=[common], help="Process due recurring transactions")

    review = commands.add_parser("review-future", parents=[common], help="Read-only future-entry inventory")
    review.add_argument("--limit", type=int, default=100)
    review.add_argument("--offset", type=int, default=0)

    transfer = commands.add_parser(
        "migrate-postgres", parents=[common], help="Verify and copy SQLite to PostgreSQL"
    )
    transfer.add_argument("--yes", action="store_true", help="Commit the verified copy; default is dry-run")

    restore = commands.add_parser("restore", parents=[common], help="Restore a verified backup archive")
    restore.add_argument("backup", type=Path, help="Backup archive to restore")
    restore.add_argument(
        "--yes",
        action="store_true",
        help="Confirm replacement of the configured database",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    service = BackupService(args.database or settings.database_path)

    try:
        if args.command == "review-future":
            url = (
                settings.database_url.get_secret_value()
                if settings.database_url and not args.database
                else None
            )
            _print_json(
                review_future_entries(args.database or settings.database_path, url, args.limit, args.offset)
            )
            return 0
        if args.command == "migrate-postgres":
            if settings.database_url is None:
                raise ValueError("Set DATABASE_URL to the empty PostgreSQL destination")
            _print_json(
                transfer_sqlite(
                    args.database or settings.database_path,
                    settings.database_url.get_secret_value(),
                    settings.base_currency,
                    commit=args.yes,
                )
            )
            return 0
        if args.command == "process-recurring":
            database = (
                FinanceDatabase(args.database, settings.base_currency)
                if args.database
                else open_database(settings)
            )
            database.close()
            created = process_recurring(database)
            _print_json({"status": "ok", "created": created})
            return 0

        if settings.database_url and args.database is None:
            raise ValueError(
                "SQLite recovery commands require --database while PostgreSQL is configured; "
                "use pg_dump/pg_restore for PostgreSQL"
            )

        if args.command == "integrity":
            report = service.integrity_check()
            _print_json(report.to_dict())
            return 0 if report.ok else 1

        if args.command == "backup":
            backup = service.create_backup(args.destination)
            _print_json({"status": "ok", "backup": str(backup)})
            return 0

        if not args.yes:
            _print_json(
                {"status": "error", "error": "Restore requires the --yes confirmation flag"},
                stream=sys.stderr,
            )
            return 2
        result = service.restore_backup(args.backup)
        _print_json({"status": "ok", **result.to_dict()})
        return 0
    except psycopg.Error:
        _print_json(
            {
                "status": "error",
                "error": "PostgreSQL operation failed; no credentials or row data are logged",
            },
            stream=sys.stderr,
        )
        return 1
    except (BackupError, sqlite3.Error, ValueError, RuntimeError) as exc:
        _print_json({"status": "error", "error": str(exc)}, stream=sys.stderr)
        return 1


def _print_json(value: dict, stream=None) -> None:
    print(json.dumps(value, indent=2, sort_keys=True), file=stream or sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())

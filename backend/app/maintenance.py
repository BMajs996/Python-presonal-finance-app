import argparse
import json
import sys
from pathlib import Path

from .core.config import settings
from .services.backup_service import BackupError, BackupService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finance Dashboard database recovery tools")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--database",
        type=Path,
        default=settings.database_path,
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
    service = BackupService(args.database)

    try:
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
    except BackupError as exc:
        _print_json({"status": "error", "error": str(exc)}, stream=sys.stderr)
        return 1


def _print_json(value: dict, stream=None) -> None:
    print(json.dumps(value, indent=2, sort_keys=True), file=stream or sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())

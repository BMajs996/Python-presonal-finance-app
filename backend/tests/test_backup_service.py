import hashlib
import json
import sqlite3
import stat
import zipfile
from datetime import date
from pathlib import Path

import pytest
from app.database import FinanceDatabase
from app.maintenance import main
from app.migrations import LATEST_SCHEMA_VERSION
from app.repositories.finance_repository import FinanceRepository
from app.schemas import TransactionCreate
from app.services.backup_service import (
    DATABASE_MEMBER,
    MANIFEST_MEMBER,
    BackupError,
    BackupService,
)


def add_transaction(repository, description: str):
    return repository.add_transaction(
        TransactionCreate(
            date=date.today(),
            type="income",
            category="Salary",
            amount="123.45",
            description=description,
        )
    )


def open_repository(path):
    database = FinanceDatabase(path)
    return FinanceRepository(database)


def test_backup_archive_contains_verified_snapshot_and_manifest(db, tmp_path):
    add_transaction(db, "Included from live database")
    archive_path = BackupService(db.database.db_path).create_backup(tmp_path / "archives")

    assert archive_path.suffix == ".financebackup"
    assert stat.S_IMODE(archive_path.stat().st_mode) == 0o600
    with zipfile.ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == {MANIFEST_MEMBER, DATABASE_MEMBER}
        manifest = json.loads(archive.read(MANIFEST_MEMBER))
        database_bytes = archive.read(DATABASE_MEMBER)

    assert manifest["format"] == "finance-dashboard-backup"
    assert manifest["format_version"] == 1
    assert manifest["schema_version"] == LATEST_SCHEMA_VERSION
    assert manifest["database_size"] == len(database_bytes)
    assert manifest["database_sha256"] == hashlib.sha256(database_bytes).hexdigest()


def test_backup_round_trip_restores_transactions(db, tmp_path):
    add_transaction(db, "Round trip")
    archive_path = BackupService(db.database.db_path).create_backup(tmp_path / "backup.financebackup")
    restored_path = tmp_path / "restored.db"

    result = BackupService(restored_path).restore_backup(archive_path)

    assert result.safety_backup is None
    assert result.schema_version == LATEST_SCHEMA_VERSION
    restored = open_repository(restored_path)
    try:
        transactions, total = restored.list_transactions()
        assert total == 1
        assert transactions[0]["description"] == "Round trip"
    finally:
        restored.close()


def test_restore_preserves_existing_database_in_safety_archive(tmp_path):
    source = open_repository(tmp_path / "source.db")
    add_transaction(source, "Replacement data")
    archive_path = BackupService(source.database.db_path).create_backup(tmp_path / "source.financebackup")
    source.close()

    target_path = tmp_path / "target.db"
    target = open_repository(target_path)
    add_transaction(target, "Original data")
    target.close()

    result = BackupService(target_path).restore_backup(archive_path)

    assert result.safety_backup is not None
    safety_archive = result.safety_backup
    assert safety_archive and BackupService(target_path).integrity_check().ok

    safety_restore_path = tmp_path / "safety-restored.db"
    BackupService(safety_restore_path).restore_backup(safety_archive)
    safety = open_repository(safety_restore_path)
    replacement = open_repository(target_path)
    try:
        assert safety.list_transactions()[0][0]["description"] == "Original data"
        assert replacement.list_transactions()[0][0]["description"] == "Replacement data"
    finally:
        safety.close()
        replacement.close()


def test_restore_rejects_tampered_database_checksum(db, tmp_path):
    archive_path = BackupService(db.database.db_path).create_backup(tmp_path / "valid.financebackup")
    tampered_path = tmp_path / "tampered.financebackup"
    with zipfile.ZipFile(archive_path) as source, zipfile.ZipFile(tampered_path, "w") as target:
        target.writestr(MANIFEST_MEMBER, source.read(MANIFEST_MEMBER))
        target.writestr(DATABASE_MEMBER, source.read(DATABASE_MEMBER) + b"tampered")

    with pytest.raises(BackupError, match="size does not match"):
        BackupService(tmp_path / "restored.db").restore_backup(tampered_path)


def test_integrity_check_reports_missing_and_corrupt_databases(tmp_path):
    missing = BackupService(tmp_path / "missing.db").integrity_check()
    assert not missing.ok
    assert missing.integrity_messages == ["Database file does not exist"]

    corrupt_path = tmp_path / "corrupt.db"
    corrupt_path.write_bytes(b"this is not sqlite")
    corrupt = BackupService(corrupt_path).integrity_check()
    assert not corrupt.ok
    assert corrupt.schema_version is None


def test_restore_rejects_a_database_from_a_future_schema(db, tmp_path):
    archive_path = BackupService(db.database.db_path).create_backup(tmp_path / "current.financebackup")
    future_database = tmp_path / "future.db"
    with zipfile.ZipFile(archive_path) as archive:
        future_database.write_bytes(archive.read(DATABASE_MEMBER))
        manifest = json.loads(archive.read(MANIFEST_MEMBER))

    connection = sqlite3.connect(future_database)
    connection.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (LATEST_SCHEMA_VERSION + 1, "2026-08-31T00:00:00+00:00"),
    )
    connection.commit()
    connection.close()
    database_bytes = future_database.read_bytes()
    manifest["schema_version"] = LATEST_SCHEMA_VERSION + 1
    manifest["database_size"] = len(database_bytes)
    manifest["database_sha256"] = hashlib.sha256(database_bytes).hexdigest()

    future_archive = tmp_path / "future.financebackup"
    with zipfile.ZipFile(future_archive, "w") as archive:
        archive.writestr(MANIFEST_MEMBER, json.dumps(manifest))
        archive.writestr(DATABASE_MEMBER, database_bytes)

    with pytest.raises(BackupError, match="newer than supported"):
        BackupService(tmp_path / "restored.db").restore_backup(future_archive)


def test_restore_preserves_and_replaces_a_corrupt_destination(db, tmp_path):
    add_transaction(db, "Recovered data")
    archive_path = BackupService(db.database.db_path).create_backup(tmp_path / "recovery.financebackup")
    corrupt_destination = tmp_path / "corrupt-destination.db"
    corrupt_bytes = b"unreadable database contents"
    corrupt_destination.write_bytes(corrupt_bytes)

    result = BackupService(corrupt_destination).restore_backup(archive_path)

    assert result.safety_backup is not None
    preserved = result.safety_backup
    assert preserved and preserved.endswith(".sqlite3")
    assert Path(preserved).read_bytes() == corrupt_bytes
    assert BackupService(corrupt_destination).integrity_check().ok


def test_maintenance_cli_checks_backs_up_and_requires_restore_confirmation(db, tmp_path, capsys):
    database_path = str(db.database.db_path)
    archive_path = tmp_path / "cli.financebackup"

    assert main(["integrity", "--database", database_path]) == 0
    integrity_output = json.loads(capsys.readouterr().out)
    assert integrity_output["ok"] is True

    assert main(["backup", "--database", database_path, str(archive_path)]) == 0
    backup_output = json.loads(capsys.readouterr().out)
    assert backup_output == {"status": "ok", "backup": str(archive_path)}

    restored_path = tmp_path / "cli-restored.db"
    assert main(["restore", "--database", str(restored_path), str(archive_path)]) == 2
    assert "--yes" in json.loads(capsys.readouterr().err)["error"]

    assert main(["restore", "--database", str(restored_path), str(archive_path), "--yes"]) == 0
    restore_output = json.loads(capsys.readouterr().out)
    assert restore_output["status"] == "ok"
    assert BackupService(restored_path).integrity_check().ok

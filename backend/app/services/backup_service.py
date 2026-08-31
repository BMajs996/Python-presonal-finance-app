import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..migrations import LATEST_SCHEMA_VERSION

BACKUP_FORMAT = "finance-dashboard-backup"
BACKUP_FORMAT_VERSION = 1
DATABASE_MEMBER = "database.sqlite3"
MANIFEST_MEMBER = "manifest.json"
MAX_BACKUP_BYTES = 10 * 1024 * 1024 * 1024


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    ok: bool
    database: str
    schema_version: int | None
    size_bytes: int
    integrity_messages: list[str]
    foreign_key_errors: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RestoreResult:
    database: str
    backup: str
    safety_backup: str | None
    schema_version: int

    def to_dict(self) -> dict:
        return asdict(self)


class BackupService:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path).expanduser().resolve()

    def integrity_check(self, database_path: str | Path | None = None) -> IntegrityReport:
        path = Path(database_path or self.database_path).expanduser().resolve()
        if not path.is_file():
            return IntegrityReport(False, str(path), None, 0, ["Database file does not exist"], 0)

        try:
            connection = self._read_only_connection(path)
            try:
                messages = [row[0] for row in connection.execute("PRAGMA integrity_check")]
                foreign_key_errors = len(connection.execute("PRAGMA foreign_key_check").fetchall())
                schema_version = self._schema_version(connection)
            finally:
                connection.close()
        except sqlite3.DatabaseError as exc:
            return IntegrityReport(False, str(path), None, path.stat().st_size, [str(exc)], 0)

        ok = messages == ["ok"] and foreign_key_errors == 0
        return IntegrityReport(
            ok,
            str(path),
            schema_version,
            path.stat().st_size,
            messages,
            foreign_key_errors,
        )

    def create_backup(self, destination: str | Path | None = None, prefix: str = "finance-backup") -> Path:
        if not self.database_path.is_file():
            raise BackupError(f"Database file does not exist: {self.database_path}")

        target = self._backup_target(destination, prefix)
        if target.exists():
            raise BackupError(f"Backup already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)

        database_temp = self._temporary_path(target.parent, ".sqlite3")
        archive_temp = self._temporary_path(target.parent, ".financebackup")
        try:
            try:
                self._snapshot_database(self.database_path, database_temp)
                report = self.integrity_check(database_temp)
                if not report.ok or report.schema_version is None:
                    raise BackupError(f"Backup snapshot failed integrity check: {report.integrity_messages}")

                manifest = {
                    "format": BACKUP_FORMAT,
                    "format_version": BACKUP_FORMAT_VERSION,
                    "created_at": datetime.now(UTC).isoformat(),
                    "schema_version": report.schema_version,
                    "database_sha256": self._sha256(database_temp),
                    "database_size": database_temp.stat().st_size,
                }
                with zipfile.ZipFile(archive_temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr(MANIFEST_MEMBER, json.dumps(manifest, indent=2, sort_keys=True))
                    archive.write(database_temp, DATABASE_MEMBER)

                os.chmod(archive_temp, 0o600)
                os.replace(archive_temp, target)
                return target
            except (OSError, sqlite3.DatabaseError, zipfile.BadZipFile) as exc:
                raise BackupError(f"Could not create backup: {exc}") from exc
        finally:
            database_temp.unlink(missing_ok=True)
            archive_temp.unlink(missing_ok=True)

    def restore_backup(self, backup_path: str | Path) -> RestoreResult:
        backup = Path(backup_path).expanduser().resolve()
        if not backup.is_file():
            raise BackupError(f"Backup file does not exist: {backup}")

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        restored_temp = self._temporary_path(self.database_path.parent, ".sqlite3")
        safety_backup = None
        try:
            manifest = self._extract_verified_database(backup, restored_temp)
            report = self.integrity_check(restored_temp)
            if not report.ok:
                raise BackupError(f"Restored database failed integrity check: {report.integrity_messages}")
            schema_version = report.schema_version
            if schema_version is None:
                raise BackupError("Restored database schema version could not be determined")
            if schema_version != manifest["schema_version"]:
                raise BackupError("Backup manifest schema version does not match the database")
            if schema_version > LATEST_SCHEMA_VERSION:
                raise BackupError(
                    f"Backup schema {schema_version} is newer than supported schema {LATEST_SCHEMA_VERSION}"
                )

            if self.database_path.exists():
                self._assert_exclusive_access(self.database_path)
                existing_service = BackupService(self.database_path)
                try:
                    safety_backup = existing_service.create_backup(
                        self.database_path.parent / "backups", prefix="pre-restore"
                    )
                except BackupError:
                    if existing_service.integrity_check().ok:
                        raise
                    safety_backup = self._preserve_corrupt_database(self.database_path)

            os.chmod(restored_temp, 0o600)
            os.replace(restored_temp, self.database_path)
            self._remove_sqlite_sidecars(self.database_path)
            return RestoreResult(
                str(self.database_path),
                str(backup),
                str(safety_backup) if safety_backup else None,
                schema_version,
            )
        finally:
            restored_temp.unlink(missing_ok=True)

    def _extract_verified_database(self, backup: Path, destination: Path) -> dict:
        try:
            with zipfile.ZipFile(backup, "r") as archive:
                if set(archive.namelist()) != {MANIFEST_MEMBER, DATABASE_MEMBER}:
                    raise BackupError("Backup archive has an invalid file layout")
                database_info = archive.getinfo(DATABASE_MEMBER)
                if database_info.file_size > MAX_BACKUP_BYTES:
                    raise BackupError("Backup database exceeds the supported size limit")
                manifest = json.loads(archive.read(MANIFEST_MEMBER))
                self._validate_manifest(manifest)

                digest = hashlib.sha256()
                with archive.open(DATABASE_MEMBER) as source, destination.open("wb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
                        digest.update(chunk)
        except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            raise BackupError(f"Invalid backup archive: {exc}") from exc

        if destination.stat().st_size != manifest["database_size"]:
            raise BackupError("Backup database size does not match its manifest")
        if not hmac.compare_digest(digest.hexdigest(), manifest["database_sha256"]):
            raise BackupError("Backup database checksum does not match its manifest")
        return manifest

    @staticmethod
    def _validate_manifest(manifest: dict) -> None:
        required = {
            "format": str,
            "format_version": int,
            "created_at": str,
            "schema_version": int,
            "database_sha256": str,
            "database_size": int,
        }
        if not isinstance(manifest, dict) or any(
            key not in manifest or not isinstance(manifest[key], expected)
            for key, expected in required.items()
        ):
            raise BackupError("Backup manifest is incomplete or invalid")
        if manifest["format"] != BACKUP_FORMAT:
            raise BackupError("Unsupported backup format")
        if manifest["format_version"] != BACKUP_FORMAT_VERSION:
            raise BackupError("Unsupported backup format version")
        if manifest["schema_version"] < 0 or manifest["database_size"] < 0:
            raise BackupError("Backup manifest contains invalid numeric values")

    @staticmethod
    def _snapshot_database(source_path: Path, destination_path: Path) -> None:
        source = BackupService._read_only_connection(source_path)
        destination = sqlite3.connect(destination_path)
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
            source.close()

    @staticmethod
    def _read_only_connection(path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> int:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        if not table:
            return 0
        return int(
            connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _backup_target(self, destination: str | Path | None, prefix: str) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        filename = f"{prefix}-{timestamp}.financebackup"
        if destination is None:
            return self.database_path.parent / "backups" / filename
        path = Path(destination).expanduser().resolve()
        if path.suffix == ".financebackup":
            return path
        return path / filename

    @staticmethod
    def _temporary_path(directory: Path, suffix: str) -> Path:
        descriptor, name = tempfile.mkstemp(prefix=".finance-", suffix=suffix, dir=directory)
        os.close(descriptor)
        return Path(name)

    @staticmethod
    def _assert_exclusive_access(path: Path) -> None:
        connection = None
        try:
            connection = sqlite3.connect(path, timeout=0)
            connection.execute("BEGIN EXCLUSIVE")
            connection.rollback()
        except sqlite3.DatabaseError as exc:
            message = str(exc).lower()
            if "locked" in message or "busy" in message:
                raise BackupError("Database is busy; stop the application before restoring") from exc
            if BackupService(path).integrity_check().ok:
                raise BackupError("Could not acquire exclusive database access") from exc
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _preserve_corrupt_database(path: Path) -> Path:
        backup_directory = path.parent / "backups"
        backup_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        preserved = backup_directory / f"pre-restore-corrupt-{timestamp}.sqlite3"
        shutil.copy2(path, preserved)
        os.chmod(preserved, 0o600)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{path}{suffix}")
            if sidecar.exists():
                preserved_sidecar = Path(f"{preserved}{suffix}")
                shutil.copy2(sidecar, preserved_sidecar)
                os.chmod(preserved_sidecar, 0o600)
        return preserved

    @staticmethod
    def _remove_sqlite_sidecars(path: Path) -> None:
        Path(f"{path}-wal").unlink(missing_ok=True)
        Path(f"{path}-shm").unlink(missing_ok=True)

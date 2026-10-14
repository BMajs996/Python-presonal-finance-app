"""User credentials, bounded hashing and revocable database-backed sessions."""

import hashlib
import secrets
import sqlite3
import time
from threading import BoundedSemaphore
from uuid import uuid4

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException

from ..core.config import settings

PASSWORDS = PasswordHasher()
HASH_SLOTS = BoundedSemaphore(2)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
COOKIE = "finance_session"
RATE_QUERIES = (
    (
        "DELETE FROM auth_source_limits WHERE window_start<=?",
        "SELECT * FROM auth_source_limits WHERE source_key=?",
        "INSERT INTO auth_source_limits VALUES (?,?,1) ON CONFLICT(source_key) "
        "DO UPDATE SET attempts=auth_source_limits.attempts+1",
        10,
    ),
    (
        "DELETE FROM auth_account_limits WHERE window_start<=?",
        "SELECT * FROM auth_account_limits WHERE account_key=?",
        "INSERT INTO auth_account_limits VALUES (?,?,1) ON CONFLICT(account_key) "
        "DO UPDATE SET attempts=auth_account_limits.attempts+1",
        30,
    ),
)
AUTH_TABLES = {
    "auth_sessions",
    "auth_login_limit",
    "auth_source_limits",
    "auth_account_limits",
    "auth_codes",
    "auth_security_events",
}


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def owner_key() -> str:
    configured = settings.owner_password_hash
    return token_hash(settings.owner_username + ":" + (configured.get_secret_value() if configured else ""))


def initialize_auth(database):
    with database.operational_transaction() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, owner_key TEXT NOT NULL,
            expires_at BIGINT NOT NULL, last_seen BIGINT NOT NULL,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            auth_version BIGINT NOT NULL, session_id TEXT NOT NULL UNIQUE, created_at BIGINT NOT NULL)""")
        if isinstance(connection, sqlite3.Connection):
            columns = {row[1] for row in connection.execute("PRAGMA table_info(auth_sessions)")}
        else:
            columns = {
                row[0]
                for row in connection.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name='auth_sessions'"
                )
            }
        if "user_id" not in columns:
            # Legacy owner sessions must not survive the authentication contract upgrade.
            connection.execute("DELETE FROM auth_sessions")
            for name, definition in (
                ("user_id", "BIGINT NOT NULL DEFAULT 1 REFERENCES users(id) ON DELETE RESTRICT"),
                ("auth_version", "BIGINT NOT NULL DEFAULT 0"),
                ("session_id", "TEXT"),
                ("created_at", "BIGINT NOT NULL DEFAULT 0"),
            ):
                connection.execute(f"ALTER TABLE auth_sessions ADD COLUMN {name} {definition}")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_session_id ON auth_sessions(session_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON auth_sessions(user_id,last_seen)")
        connection.execute("""CREATE TABLE IF NOT EXISTS auth_login_limit (
            id INTEGER PRIMARY KEY CHECK(id=1), window_start BIGINT NOT NULL, attempts INTEGER NOT NULL)""")
        connection.execute("INSERT INTO auth_login_limit VALUES (1,0,0) ON CONFLICT(id) DO NOTHING")
        for table, column in (("auth_source_limits", "source_key"), ("auth_account_limits", "account_key")):
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {table} "
                f"({column} TEXT PRIMARY KEY, window_start BIGINT NOT NULL, attempts INTEGER NOT NULL)"
            )
            connection.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_window ON {table}(window_start)")
        for column in ("expires_at", "last_seen"):
            connection.execute(f"CREATE INDEX IF NOT EXISTS idx_sessions_{column} ON auth_sessions({column})")
        connection.execute("""CREATE TABLE IF NOT EXISTS auth_codes (
            token_hash TEXT PRIMARY KEY, purpose TEXT NOT NULL CHECK(purpose IN ('invite','reset')),
            target_key TEXT NOT NULL, user_id BIGINT REFERENCES users(id) ON DELETE RESTRICT,
            expires_at BIGINT NOT NULL, UNIQUE(purpose,target_key))""")
        connection.execute("""CREATE TABLE IF NOT EXISTS auth_security_events (
            event_id TEXT PRIMARY KEY, user_id BIGINT REFERENCES users(id) ON DELETE RESTRICT,
            event TEXT NOT NULL, occurred_at BIGINT NOT NULL)""")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_events_time ON auth_security_events(occurred_at)"
        )
        configured = settings.owner_password_hash
        owner = connection.execute("SELECT bootstrap_key FROM users WHERE id=1").fetchone()
        if configured and owner["bootstrap_key"] != owner_key():
            connection.execute(
                """UPDATE users SET username=?,username_key=?,
                display_name=CASE WHEN display_name='' THEN ? ELSE display_name END,password_hash=?,
                bootstrap_key=?,auth_version=auth_version+1 WHERE id=1""",
                (
                    settings.owner_username,
                    settings.owner_username.casefold(),
                    settings.owner_username,
                    configured.get_secret_value(),
                    owner_key(),
                ),
            )
            connection.execute("DELETE FROM auth_sessions WHERE user_id=1")


def hash_password(password: str) -> str:
    if not 15 <= len(password) <= 1024:
        raise HTTPException(422, "Password must contain 15 to 1024 characters")
    try:
        password.encode("utf-8")
    except UnicodeError:
        raise HTTPException(422, "Password contains invalid Unicode characters") from None
    if not HASH_SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Sign-in is busy. Try again shortly.", headers={"Retry-After": "1"})
    try:
        return PASSWORDS.hash(password)
    finally:
        HASH_SLOTS.release()


def verify_password(encoded: str | None, password: str) -> bool:
    if not HASH_SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Sign-in is busy. Try again shortly.", headers={"Retry-After": "1"})
    try:
        try:
            return PASSWORDS.verify(encoded or DUMMY_HASH, password)
        except (VerificationError, ValueError):
            return False
    finally:
        HASH_SLOTS.release()


def security_event(connection, user_id, event):
    now = int(time.time())
    connection.execute("DELETE FROM auth_security_events WHERE occurred_at<=?", (now - 90 * 86400,))
    connection.execute("""DELETE FROM auth_security_events WHERE event_id IN (
        SELECT event_id FROM auth_security_events ORDER BY occurred_at DESC,event_id DESC
        LIMIT 100 OFFSET 9999)""")
    connection.execute(
        "INSERT INTO auth_security_events VALUES (?,?,?,?)", (str(uuid4()), user_id, event, now)
    )


class AuthService:
    def __init__(self, database):
        self.database = database

    def reserve(self, source: str, target: str):
        now = int(time.time())
        with self.database.operational_transaction() as connection:
            keys = (token_hash(source), token_hash(target))
            for (purge, select, _insert, limit), key in zip(RATE_QUERIES, keys, strict=True):
                connection.execute(purge, (now - 60,))
                row = connection.execute(select, (key,)).fetchone()
                if row and row["attempts"] >= limit:
                    raise HTTPException(
                        429,
                        "Too many sign-in attempts. Try again shortly.",
                        headers={"Retry-After": str(max(1, 60 - (now - row["window_start"])))},
                    )
            row = connection.execute("SELECT * FROM auth_login_limit WHERE id=1").fetchone()
            count = row["attempts"] if now - row["window_start"] < 60 else 0
            start = row["window_start"] if count else now
            if count >= 100:
                raise HTTPException(
                    429,
                    "Too many sign-in attempts. Try again shortly.",
                    headers={"Retry-After": str(max(1, 60 - (now - start)))},
                )
            connection.execute(
                "UPDATE auth_login_limit SET window_start=?,attempts=? WHERE id=1", (start, count + 1)
            )
            for (_purge, _select, insert, _limit), key in zip(RATE_QUERIES, keys, strict=True):
                connection.execute(insert, (key, now))

    def login(self, username: str, password: str, previous: str | None, source: str = "local"):
        identifier = username.strip().casefold()
        with self.database.connection() as connection:
            query = (
                "SELECT * FROM users WHERE email_key=?"
                if "@" in identifier and identifier != settings.owner_username.casefold()
                else "SELECT * FROM users WHERE username_key=?"
            )
            user = connection.execute(query, (identifier,)).fetchone()
        if (
            user and user["id"] == 1 or identifier == settings.owner_username.casefold()
        ) and not settings.owner_password_hash:
            raise HTTPException(503, "Owner access has not been configured")
        self.reserve(source, "user:" + str(user["id"]) if user else "login:" + identifier)
        valid = verify_password(user["password_hash"] if user else None, password)
        if (
            not valid
            or not user
            or not user["active"]
            or not user["password_hash"]
            or (user["id"] == 1 and user["bootstrap_key"] != owner_key())
        ):
            with self.database.operational_transaction() as connection:
                security_event(connection, user["id"] if user else None, "sign_in_failed")
            raise HTTPException(401, "Invalid username or password")
        now = int(time.time())
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.database.operational_transaction() as connection:
            # Recheck under the auth writer reservation after expensive password verification.
            current = connection.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            if not current["active"] or current["auth_version"] != user["auth_version"]:
                raise HTTPException(401, "Invalid username or password")
            connection.execute(
                "DELETE FROM auth_sessions WHERE expires_at<=? OR last_seen<=?",
                (now, now - settings.session_idle_seconds),
            )
            if previous:
                connection.execute(
                    "DELETE FROM auth_sessions WHERE token_hash=? AND user_id=?",
                    (token_hash(previous), user["id"]),
                )
            # At most five active sessions per user, including the new session.
            connection.execute(
                """DELETE FROM auth_sessions WHERE user_id=? AND token_hash NOT IN (
                SELECT token_hash FROM auth_sessions WHERE user_id=?
                ORDER BY last_seen DESC,token_hash LIMIT 4)""",
                (user["id"], user["id"]),
            )
            connection.execute(
                """INSERT INTO auth_sessions(
                token_hash,csrf,owner_key,expires_at,last_seen,user_id,auth_version,session_id,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    token_hash(token),
                    csrf,
                    owner_key() if user["id"] == 1 else "",
                    now + settings.session_seconds,
                    now,
                    user["id"],
                    user["auth_version"],
                    str(uuid4()),
                    now,
                ),
            )
            security_event(connection, user["id"], "signed_in")
        return token, csrf

    def session(self, token: str | None):
        if not token or len(token) > 128:
            return None
        now = int(time.time())
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT s.*,u.username,u.display_name,u.is_admin
                FROM auth_sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.auth_version=u.auth_version AND u.active=1
                AND s.expires_at>? AND s.last_seen>?""",
                (token_hash(token), now, now - settings.session_idle_seconds),
            ).fetchone()
            if row is None or (
                row["user_id"] == 1
                and (
                    not settings.owner_password_hash
                    or not secrets.compare_digest(row["owner_key"], owner_key())
                )
            ):
                return None
            threshold = min(60, max(1, settings.session_idle_seconds // 4))
            if row["last_seen"] <= now - threshold:
                if isinstance(connection, sqlite3.Connection):
                    connection.execute("PRAGMA busy_timeout=0")
                else:
                    connection.execute("SET lock_timeout='100ms'")
                try:
                    connection.execute(
                        """UPDATE auth_sessions SET last_seen=? WHERE token_hash=?
                        AND expires_at>? AND last_seen>? AND last_seen<=?""",
                        (now, token_hash(token), now, now - settings.session_idle_seconds, now - threshold),
                    )
                    connection.commit()
                except sqlite3.OperationalError as exc:
                    connection.rollback()
                    if getattr(exc, "sqlite_errorcode", 0) & 255 not in {
                        sqlite3.SQLITE_BUSY,
                        sqlite3.SQLITE_LOCKED,
                    }:
                        raise
                except psycopg.errors.LockNotAvailable:
                    connection.rollback()
            return dict(row)

    def logout(self, token: str):
        with self.database.operational_transaction() as connection:
            connection.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash(token),))

    def sessions(self, user_id: int, current: str):
        now = int(time.time())
        with self.database.connection() as connection:
            rows = connection.execute(
                """SELECT session_id,created_at,last_seen,expires_at,token_hash
                FROM auth_sessions WHERE user_id=?
                AND auth_version=(SELECT auth_version FROM users WHERE id=?) AND expires_at>? AND last_seen>?
                ORDER BY created_at DESC,session_id LIMIT 5""",
                (user_id, user_id, now, now - settings.session_idle_seconds),
            ).fetchall()
        return [
            {
                "session_id": row["session_id"],
                "created_at": row["created_at"],
                "last_seen": row["last_seen"],
                "expires_at": row["expires_at"],
                "current": row["token_hash"] == token_hash(current),
            }
            for row in rows
        ]

    def revoke(self, user_id: int, session_id: str, source="local"):
        self.reserve(source, "user:" + str(user_id))
        with self.database.operational_transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM auth_sessions WHERE user_id=? AND session_id=?", (user_id, session_id)
            )
            if not cursor.rowcount:
                raise HTTPException(404, "Session not found")
            security_event(connection, user_id, "session_revoked")

    def revoke_others(self, user_id: int, current: str, source="local"):
        self.reserve(source, "user:" + str(user_id))
        with self.database.operational_transaction() as connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE user_id=? AND token_hash<>?", (user_id, token_hash(current))
            )
            security_event(connection, user_id, "other_sessions_revoked")

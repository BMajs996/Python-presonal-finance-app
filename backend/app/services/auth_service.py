"""Single-owner credentials and revocable, database-backed sessions."""

import hashlib
import secrets
import sqlite3
import time
from threading import BoundedSemaphore

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException

from ..core.config import settings

PASSWORDS = PasswordHasher()
HASH_SLOTS = BoundedSemaphore(2)
COOKIE = "finance_session"
AUTH_TABLES = {"auth_sessions", "auth_login_limit", "auth_source_limits"}


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def initialize_auth(database):
    with database.connection() as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, owner_key TEXT NOT NULL,
            expires_at BIGINT NOT NULL, last_seen BIGINT NOT NULL)"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS auth_login_limit (
            id INTEGER PRIMARY KEY CHECK (id=1), window_start BIGINT NOT NULL,
            attempts INTEGER NOT NULL)"""
        )
        connection.execute("INSERT INTO auth_login_limit VALUES (1,0,0) ON CONFLICT (id) DO NOTHING")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS auth_source_limits (
            source_key TEXT PRIMARY KEY, window_start BIGINT NOT NULL, attempts INTEGER NOT NULL)"""
        )


def owner_key() -> str:
    password_hash = settings.owner_password_hash
    return token_hash(
        settings.owner_username + ":" + (password_hash.get_secret_value() if password_hash else "")
    )


class AuthService:
    def __init__(self, database):
        self.database = database

    def login(self, username: str, password: str, previous: str | None, source: str = "local"):
        configured = settings.owner_password_hash
        if not configured:
            raise HTTPException(503, "Owner access has not been configured")
        now = int(time.time())
        # Bound each source first, then reserve global hashing capacity across workers.
        with self.database.operational_transaction() as connection:
            key = token_hash(source)
            connection.execute("DELETE FROM auth_source_limits WHERE window_start<=?", (now - 60,))
            source_row = connection.execute(
                "SELECT * FROM auth_source_limits WHERE source_key=?", (key,)
            ).fetchone()
            if source_row and source_row["attempts"] >= 10:
                raise HTTPException(
                    429,
                    "Too many sign-in attempts. Try again shortly.",
                    headers={"Retry-After": str(max(1, 60 - (now - source_row["window_start"])))},
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
                "UPDATE auth_login_limit SET window_start=?, attempts=? WHERE id=1",
                (start, count + 1),
            )
            connection.execute(
                """INSERT INTO auth_source_limits VALUES (?,?,1)
                ON CONFLICT (source_key) DO UPDATE SET attempts=auth_source_limits.attempts+1""",
                (key, now),
            )
        if not HASH_SLOTS.acquire(blocking=False):
            raise HTTPException(429, "Sign-in is busy. Try again shortly.", headers={"Retry-After": "1"})
        valid: bool
        try:
            try:
                valid = PASSWORDS.verify(configured.get_secret_value(), password)
            except (VerificationError, ValueError):
                valid = False
        finally:
            HASH_SLOTS.release()
        if not valid or not secrets.compare_digest(username.encode(), settings.owner_username.encode()):
            raise HTTPException(401, "Invalid username or password")

        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.database.operational_transaction() as connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE expires_at<=? OR last_seen<=?",
                (now, now - settings.session_idle_seconds),
            )
            if previous:
                connection.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash(previous),))
            connection.execute(
                "INSERT INTO auth_sessions VALUES (?,?,?,?,?)",
                (token_hash(token), csrf, owner_key(), now + settings.session_seconds, now),
            )
        return token, csrf

    def session(self, token: str | None):
        if not token or len(token) > 128 or not settings.owner_password_hash:
            return None
        now = int(time.time())
        with self.database.connection() as connection:
            row = connection.execute(
                """SELECT * FROM auth_sessions WHERE token_hash=? AND owner_key=?
                AND expires_at>? AND last_seen>?""",
                (token_hash(token), owner_key(), now, now - settings.session_idle_seconds),
            ).fetchone()
            if row is None:
                return None
            threshold = min(60, max(1, settings.session_idle_seconds // 4))
            if row["last_seen"] <= now - threshold:
                # Activity tracking is best-effort; a busy writer must not stall a valid read.
                if isinstance(connection, sqlite3.Connection):
                    connection.execute("PRAGMA busy_timeout=0")
                else:
                    connection.execute("SET lock_timeout='100ms'")
                try:
                    connection.execute(
                        """UPDATE auth_sessions SET last_seen=?
                        WHERE token_hash=? AND owner_key=? AND expires_at>?
                        AND last_seen>? AND last_seen<=?""",
                        (
                            now,
                            token_hash(token),
                            owner_key(),
                            now,
                            now - settings.session_idle_seconds,
                            now - threshold,
                        ),
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

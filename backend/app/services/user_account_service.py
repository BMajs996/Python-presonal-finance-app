"""Invite-only accounts and administrator-issued, single-use recovery links."""

import secrets
import sqlite3
import time
from datetime import UTC, datetime

import psycopg
from fastapi import HTTPException

from ..domain.errors import Conflict, NotFound
from .auth_service import AuthService, hash_password, security_event, token_hash, verify_password

PROFILE_SQL = """SELECT id,username,display_name,email,phone,email_verified_at,
    phone_verified_at,is_admin,created_at
    FROM users WHERE id=? AND active=1"""


class UserAccountService:
    def __init__(self, database):
        self.database = database

    def profile(self, user_id):
        with self.database.connection() as connection:
            row = connection.execute(PROFILE_SQL, (user_id,)).fetchone()
        if not row:
            raise NotFound("User not found")
        return dict(row)

    def issue_code(self, purpose: str, target: str):
        if purpose not in {"invite", "reset"}:
            raise ValueError("Unsupported account code")
        now = int(time.time())
        token = secrets.token_urlsafe(32)
        target = target.strip().casefold()
        with self.database.operational_transaction() as connection:
            connection.execute("DELETE FROM auth_codes WHERE expires_at<=?", (now,))
            user_id = None
            if purpose == "invite":
                if connection.execute(
                    "SELECT 1 FROM users WHERE email_key=? OR username_key=?", (target, target)
                ).fetchone():
                    raise Conflict("An account already uses this email")
            else:
                user = connection.execute("SELECT id FROM users WHERE username_key=?", (target,)).fetchone()
                if not user:
                    raise NotFound("User not found")
                user_id = user["id"]
                target = str(user_id)
            connection.execute("DELETE FROM auth_codes WHERE purpose=? AND target_key=?", (purpose, target))
            if connection.execute("SELECT COUNT(*) FROM auth_codes").fetchone()[0] >= 1000:
                raise Conflict("Too many outstanding account links")
            lifetime = 48 * 3600 if purpose == "invite" else 1800
            connection.execute(
                "INSERT INTO auth_codes VALUES (?,?,?,?,?)",
                (token_hash(token), purpose, target, user_id, now + lifetime),
            )
            security_event(
                connection, user_id, "invitation_issued" if purpose == "invite" else "recovery_issued"
            )
        return token

    def register(self, payload, source):
        digest = token_hash(payload.token.get_secret_value())
        auth = AuthService(self.database)
        auth.reserve(source, "invite:" + digest)
        with self.database.connection() as connection:
            invitation = connection.execute(
                "SELECT target_key FROM auth_codes WHERE token_hash=? AND purpose='invite' AND expires_at>?",
                (digest, int(time.time())),
            ).fetchone()
        if not invitation or invitation["target_key"] != payload.email_key:
            raise HTTPException(400, "Invalid or expired invitation")
        encoded = hash_password(payload.password.get_secret_value())
        try:
            with self.database.operational_transaction() as connection:
                claim = connection.execute(
                    "DELETE FROM auth_codes WHERE token_hash=? AND purpose='invite' "
                    "AND target_key=? AND expires_at>? RETURNING token_hash",
                    (digest, payload.email_key, int(time.time())),
                ).fetchone()
                if not claim:
                    raise HTTPException(400, "Invalid or expired invitation")
                user = connection.execute(
                    """INSERT INTO users(
                    username,username_key,display_name,email,email_key,phone,password_hash,created_at)
                    VALUES (?,?,?,?,?,?,?,?) RETURNING id""",
                    (
                        payload.username,
                        payload.username.casefold(),
                        payload.display_name,
                        str(payload.email),
                        payload.email_key,
                        payload.phone,
                        encoded,
                        datetime.now(UTC).isoformat(),
                    ),
                ).fetchone()
                user_id = user["id"]
                # Account creation and token consumption share the same transaction as the credentials.
                connection.execute(
                    """INSERT INTO accounts(
                    name,type,currency,opening_balance,opening_balance_cents,active,created_at,user_id)
                    VALUES ('Main Account','checking',?,0,0,1,?,?)""",
                    (self.database.base_currency, datetime.now(UTC).isoformat(), user_id),
                )
                security_event(connection, user_id, "registered")
        except (sqlite3.IntegrityError, psycopg.errors.UniqueViolation) as exc:
            raise Conflict("Username or email is unavailable") from exc
        return self.profile(user_id)

    def reset_password(self, payload, source):
        digest = token_hash(payload.token.get_secret_value())
        AuthService(self.database).reserve(source, "reset:" + digest)
        with self.database.connection() as connection:
            code = connection.execute(
                """SELECT c.user_id FROM auth_codes c JOIN users u ON u.id=c.user_id
                WHERE c.token_hash=? AND c.purpose='reset' AND c.expires_at>?""",
                (digest, int(time.time())),
            ).fetchone()
        if not code:
            raise HTTPException(400, "Invalid or expired recovery link")
        encoded = hash_password(payload.password.get_secret_value())
        with self.database.operational_transaction() as connection:
            claim = connection.execute(
                "DELETE FROM auth_codes WHERE token_hash=? AND purpose='reset' "
                "AND expires_at>? RETURNING user_id",
                (digest, int(time.time())),
            ).fetchone()
            if not claim:
                raise HTTPException(400, "Invalid or expired recovery link")
            self._replace_password(
                connection, claim["user_id"], encoded, "password_reset", require_active=False
            )

    @staticmethod
    def _replace_password(connection, user_id, encoded, event, *, require_active=True):
        updated = connection.execute(
            "UPDATE users SET password_hash=?,auth_version=auth_version+1 WHERE id=? AND (?=0 OR active=1)",
            (encoded, user_id, int(require_active)),
        )
        if not updated.rowcount:
            raise HTTPException(400, "Account is unavailable")
        connection.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))
        connection.execute("DELETE FROM auth_codes WHERE user_id=?", (user_id,))
        security_event(connection, user_id, event)

    def _authenticate_change(self, user_id, password, source):
        AuthService(self.database).reserve(source, "user:" + str(user_id))
        with self.database.connection() as connection:
            user = connection.execute("SELECT * FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
        if not verify_password(user["password_hash"] if user else None, password) or not user:
            raise HTTPException(400, "Invalid password")
        return dict(user)

    def change_password(self, user_id, payload, source):
        user = self._authenticate_change(user_id, payload.current_password.get_secret_value(), source)
        encoded = hash_password(payload.password.get_secret_value())
        with self.database.operational_transaction() as connection:
            current = connection.execute("SELECT auth_version FROM users WHERE id=?", (user_id,)).fetchone()
            if not current or current["auth_version"] != user["auth_version"]:
                raise HTTPException(401, "Sign in again before changing the password")
            self._replace_password(connection, user_id, encoded, "password_changed")

    def update_profile(self, user_id, payload, source):
        user = self._authenticate_change(user_id, payload.current_password.get_secret_value(), source)
        try:
            with self.database.operational_transaction() as connection:
                if connection.execute(
                    "SELECT 1 FROM users WHERE id<>? AND username_key=?", (user_id, payload.email_key)
                ).fetchone():
                    raise Conflict("Email is unavailable")
                updated = connection.execute(
                    """UPDATE users SET display_name=?,email=?,email_key=?,phone=?,
                    email_verified_at=CASE WHEN email_key=? THEN email_verified_at ELSE NULL END,
                    phone_verified_at=CASE WHEN phone=? THEN phone_verified_at ELSE NULL END,
                    email_notifications=CASE WHEN email_key=? THEN email_notifications ELSE 0 END,
                    monthly_reports=CASE WHEN email_key=? THEN monthly_reports ELSE 0 END,
                    sms_notifications=CASE WHEN phone=? THEN sms_notifications ELSE 0 END
                    WHERE id=? AND active=1 AND auth_version=?""",
                    (
                        payload.display_name,
                        str(payload.email),
                        payload.email_key,
                        payload.phone,
                        payload.email_key,
                        payload.phone,
                        payload.email_key,
                        payload.email_key,
                        payload.phone,
                        user_id,
                        user["auth_version"],
                    ),
                )
                if not updated.rowcount:
                    raise HTTPException(401, "Sign in again before changing the profile")
                security_event(connection, user_id, "profile_changed")
        except (sqlite3.IntegrityError, psycopg.errors.UniqueViolation) as exc:
            raise Conflict("Email is unavailable") from exc
        return self.profile(user_id)

    def set_active(self, username, active: bool):
        with self.database.operational_transaction() as connection:
            user = connection.execute(
                "SELECT id FROM users WHERE username_key=?", (username.casefold(),)
            ).fetchone()
            if not user:
                raise NotFound("User not found")
            if user["id"] == 1 and not active:
                raise Conflict("The bootstrap administrator cannot be disabled through this command")
            connection.execute(
                "UPDATE users SET active=?,auth_version=auth_version+1 WHERE id=?", (int(active), user["id"])
            )
            connection.execute("DELETE FROM auth_sessions WHERE user_id=?", (user["id"],))
            connection.execute("DELETE FROM auth_codes WHERE user_id=?", (user["id"],))
            security_event(connection, user["id"], "account_enabled" if active else "account_disabled")

    def revoke_all(self):
        """Trusted-host recovery after a full database restore, never a public API action."""
        with self.database.operational_transaction() as connection:
            connection.execute("UPDATE users SET auth_version=auth_version+1")
            connection.execute("DELETE FROM auth_sessions")
            connection.execute("DELETE FROM auth_codes")
            security_event(connection, None, "all_sessions_revoked")

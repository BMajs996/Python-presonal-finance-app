"""Credentials belong to users; sessions/tokens remain operational metadata."""

import sqlite3

COLUMNS = {
    "username": "TEXT",
    "username_key": "TEXT",
    "display_name": "TEXT NOT NULL DEFAULT ''",
    "password_hash": "TEXT",
    "auth_version": "BIGINT NOT NULL DEFAULT 0",
    "bootstrap_key": "TEXT",
    "is_admin": "INTEGER NOT NULL DEFAULT 0 CHECK(is_admin IN (0,1))",
    "created_at": "TEXT",
}


def migrate_user_accounts(conn, _base_currency="USD"):
    for name, definition in COLUMNS.items():
        conn.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
    conn.execute("CREATE UNIQUE INDEX idx_users_username ON users(username_key)")
    conn.execute("UPDATE users SET is_admin=1 WHERE id=1")
    if not isinstance(conn, sqlite3.Connection):
        conn.execute(
            "SELECT setval(pg_get_serial_sequence('users','id'), "
            "GREATEST((SELECT MAX(id) FROM users),(SELECT last_value FROM users_id_seq)))"
        )

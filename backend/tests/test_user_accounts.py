import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from app.database import FinanceDatabase
from app.domain import business_date
from app.domain.errors import Conflict, NotFound
from app.postgres_database import PostgresDatabase
from app.repositories.finance_repository import FinanceRepository
from app.schemas import TransactionCreate
from app.services.auth_service import AuthService, initialize_auth, token_hash
from app.services.user_account_service import UserAccountService
from app.user_schemas import PasswordChange, PasswordReset, ProfileUpdate, RegistrationRequest
from fastapi import HTTPException

from .postgres_helpers import pg_url as pg_url

PASSWORD = "synthetic-member-password"
NEW_PASSWORD = "synthetic-replacement-password"


def test_auth_expiry_cleanup_uses_indexes_on_both_backends(database):
    queries = (
        ("auth_source_limits", "window_start", "idx_auth_source_limits_window"),
        ("auth_account_limits", "window_start", "idx_auth_account_limits_window"),
        ("auth_sessions", "expires_at", "idx_sessions_expires_at"),
        ("auth_sessions", "last_seen", "idx_sessions_last_seen"),
    )
    with database.connection() as connection, connection:
        for table, _column, _index in queries[:2]:
            for i in range(2000):
                connection.execute(f"INSERT INTO {table} VALUES (?,?,1)", (str(i), 0 if i < 5 else 10000))
        for i in range(2000):
            connection.execute(
                "INSERT INTO auth_sessions VALUES (?, 'csrf', 'key', ?, ?, 1, 0, ?, 0)",
                (str(i), 0 if i < 5 else 10000, 0 if i < 5 else 10000, str(i)),
            )
        for table in ("auth_source_limits", "auth_account_limits", "auth_sessions"):
            connection.execute(f"ANALYZE {table}")
        postgres = isinstance(database, PostgresDatabase)
        for table, column, index in queries:
            explain = "EXPLAIN (FORMAT JSON) " if postgres else "EXPLAIN QUERY PLAN "
            plan = connection.execute(explain + f"DELETE FROM {table} WHERE {column}<=?", (1,)).fetchall()
            details = json.dumps(plan[0][0]) if postgres else str([tuple(row) for row in plan])
            assert index in details


def test_auth_index_initialization_is_idempotent_and_preserves_sessions(database):
    from .conftest import TEST_PASSWORD

    service = AuthService(database)
    token, _csrf = service.login("owner", TEST_PASSWORD, None, "synthetic-source")
    initialize_auth(database)
    initialize_auth(database)
    assert service.session(token)["user_id"] == 1


@pytest.fixture(params=["sqlite", "postgres"])
def database(request, tmp_path):
    database = (
        PostgresDatabase(request.getfixturevalue("pg_url"))
        if request.param == "postgres"
        else FinanceDatabase(tmp_path / "users.db")
    )
    initialize_auth(database)
    try:
        yield database
    finally:
        database.close()


def registration(name="alice"):
    email = name + "@example.com"
    return RegistrationRequest(
        username=name,
        display_name=name.title(),
        email=email,
        phone="+381641234567",
        password=PASSWORD,
    )


def member(database, name="alice"):
    service = UserAccountService(database)
    payload = registration(name)
    return service.register(payload, "signup:" + name)


def test_public_registration_creates_private_unverified_member_account(database):
    service = UserAccountService(database)
    payload = registration()
    result = service.register(payload, "correct-address")
    assert result["username"] == "alice" and result["display_name"] == "Alice"
    assert result["is_admin"] == 0 and result["email_verified_at"] is None
    assert "password_hash" not in result
    with pytest.raises(Conflict):
        service.register(payload, "replayed")
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM auth_codes").fetchone()[0] == 0
        row = connection.execute("SELECT * FROM users WHERE id=?", (result["id"],)).fetchone()
        assert row["password_hash"].startswith("$argon2id$")
        assert row["password_hash"] != PASSWORD
        assert row["email_notifications"] == row["sms_notifications"] == row["monthly_reports"] == 0
        repo = FinanceRepository(database, connection=connection, user_id=result["id"])
        assert repo.list_accounts()[0]["name"] == "Main Account"
        assert repo.balances.total_cents() == 0


def test_registration_source_limit_precedes_hashing_and_survives_reinitialization(database, monkeypatch):
    from app.services import auth_service, user_account_service

    now = [1000]
    monkeypatch.setattr(auth_service.time, "time", lambda: now[0])
    auth = AuthService(database)
    for i in range(5):
        auth.reserve_registration("same-source", f"person{i}@example.com")
    initialize_auth(database)
    monkeypatch.setattr(
        user_account_service, "hash_password", lambda _value: pytest.fail("Must throttle before hashing")
    )
    with pytest.raises(HTTPException) as error:
        UserAccountService(database).register(registration(), "same-source")
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "3600"
    auth.reserve_registration("another-source", "other@example.com")
    now[0] += 60
    with pytest.raises(HTTPException) as error:
        auth.reserve_registration("same-source", "different@example.com")
    assert error.value.headers["Retry-After"] == "3540"
    now[0] = 4600
    auth.reserve_registration("same-source", "different@example.com")
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1


def test_registration_global_hour_limit_cannot_be_bypassed_with_new_sources(database, monkeypatch):
    from app.services import auth_service

    now = [1000]
    monkeypatch.setattr(auth_service.time, "time", lambda: now[0])
    auth = AuthService(database)
    for i in range(50):
        auth.reserve_registration(f"source:{i}", f"person{i}@example.com")
    now[0] += 60
    with pytest.raises(HTTPException) as error:
        auth.reserve_registration("fresh-source", "fresh@example.com")
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "3540"
    now[0] = 4600
    auth.reserve_registration("fresh-source", "fresh@example.com")


def test_concurrent_signup_reservations_cannot_exceed_source_limit(database):
    def reserve(index):
        try:
            AuthService(database).reserve_registration("shared-source", f"person{index}@example.com")
            return True
        except HTTPException as error:
            assert error.status_code == 429
            return False

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sum(workers.map(reserve, range(6))) == 5
    with database.connection() as connection:
        row = connection.execute(
            "SELECT attempts FROM auth_registration_limits WHERE bucket_key='global'"
        ).fetchone()
        assert row[0] == 5


def test_duplicate_email_is_case_insensitive_and_rejected_before_hashing(database, monkeypatch):
    from app.services import user_account_service

    member(database)
    payload = registration("bob")
    payload.email = "ALICE@example.com"
    monkeypatch.setattr(
        user_account_service,
        "hash_password",
        lambda _value: pytest.fail("Must reject duplicate before hashing"),
    )
    with pytest.raises(Conflict):
        UserAccountService(database).register(payload, "duplicate-email")


def test_registration_can_be_disabled_without_blocking_existing_users(database, monkeypatch):
    from app.core.config import settings

    member(database)
    monkeypatch.setattr(settings, "registration_enabled", False)
    with pytest.raises(HTTPException) as error:
        UserAccountService(database).register(registration("bob"), "disabled-signup")
    assert error.value.status_code == 403
    auth = AuthService(database)
    token, _csrf = auth.login("alice", PASSWORD, None, "existing-user")
    assert auth.session(token)["username"] == "alice"


def test_username_collision_creates_nothing_and_can_be_retried(database):
    service = UserAccountService(database)
    payload = registration()
    payload.username = "OWNER"
    with pytest.raises(Conflict):
        service.register(payload, "collision")
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM auth_codes").fetchone()[0] == 0
    payload.username = "alice"
    assert service.register(payload, "retry")["username"] == "alice"


def test_expired_invalid_links_are_rejected_before_hashing(database, monkeypatch):
    from app.services import user_account_service

    service = UserAccountService(database)
    member(database)
    service.issue_code("reset", "alice")
    with database.connection() as connection, connection:
        connection.execute("UPDATE auth_codes SET expires_at=0")
    monkeypatch.setattr(
        user_account_service, "hash_password", lambda _password: pytest.fail("Must not hash invalid links")
    )
    with pytest.raises(HTTPException, match="recovery"):
        service.reset_password(PasswordReset(token="x" * 43, password=NEW_PASSWORD), "invalid")


def test_concurrent_registration_creates_exactly_one_user(database):
    service = UserAccountService(database)
    payload = registration()

    def consume():
        try:
            return service.register(payload, "concurrent")["id"]
        except Conflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = [future.result(timeout=15) for future in [workers.submit(consume), workers.submit(consume)]]
    assert sum(value is not None for value in results) == 1
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 2


def test_sessions_are_per_user_revocable_and_capped(database):
    alice, bob = member(database), member(database, "bob")
    auth = AuthService(database)
    first, _ = auth.login("ALICE@EXAMPLE.COM", PASSWORD, None, "alice-one")
    second, _ = auth.login("alice", PASSWORD, None, "alice-two")
    bob_token, _ = auth.login("bob", PASSWORD, first, "bob-one")
    assert auth.session(first)["user_id"] == alice["id"]
    sessions = auth.sessions(alice["id"], first)
    assert len(sessions) == 2 and sum(row["current"] for row in sessions) == 1
    assert all("token_hash" not in row and "csrf" not in row for row in sessions)
    bob_session = auth.sessions(bob["id"], bob_token)[0]
    with pytest.raises(HTTPException) as error:
        auth.revoke(alice["id"], bob_session["session_id"], "revoke-bob")
    assert error.value.status_code == 404
    auth.revoke_others(alice["id"], first, "revoke-alice")
    assert auth.session(first) is not None and auth.session(second) is None
    assert auth.session(bob_token) is not None
    for index in range(6):
        auth.login("bob", PASSWORD, None, "bob-session:" + str(index))
    assert len(auth.sessions(bob["id"], bob_token)) == 5


def test_reset_is_single_use_preserves_data_and_revokes_only_target(database):
    alice = member(database)
    member(database, "bob")
    auth = AuthService(database)
    first, _ = auth.login("alice", PASSWORD, None, "alice-login")
    other, _ = auth.login("bob", PASSWORD, None, "bob-login")
    with database.connection() as connection:
        repo = FinanceRepository(database, connection=connection, user_id=alice["id"])
        item = repo.add_transaction(
            TransactionCreate(date=business_date.today(), type="income", category="Salary", amount="12.34")
        )
    service = UserAccountService(database)
    token = service.issue_code("reset", "alice")
    payload = PasswordReset(token=token, password=NEW_PASSWORD)
    service.reset_password(payload, "recovery")
    assert auth.session(first) is None and auth.session(other) is not None
    with pytest.raises(HTTPException):
        service.reset_password(payload, "replay")
    with pytest.raises(HTTPException) as error:
        auth.login("alice", PASSWORD, None, "old-password")
    assert error.value.status_code == 401
    new_token, _ = auth.login("alice", NEW_PASSWORD, None, "new-password")
    assert auth.session(new_token)["user_id"] == alice["id"]
    with database.connection() as connection:
        repo = FinanceRepository(database, connection=connection, user_id=alice["id"])
        assert repo.get_transaction(item["id"]) == item
        assert repo.transactions.history(item["id"])["total"] == 1


def test_concurrent_recovery_can_only_change_password_once(database):
    member(database)
    service = UserAccountService(database)
    token = service.issue_code("reset", "alice")
    payload = PasswordReset(token=token, password=NEW_PASSWORD)

    def reset():
        try:
            service.reset_password(payload, "reset-race")
            return True
        except HTTPException as error:
            assert error.status_code == 400
            return False

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(reset) for _ in range(2)]
        assert sum(future.result(timeout=15) for future in futures) == 1


def test_password_changes_persist_after_bootstrap_initialization(database):
    from .conftest import TEST_PASSWORD

    auth = AuthService(database)
    token, _ = auth.login("owner", TEST_PASSWORD, None, "owner-login")
    UserAccountService(database).change_password(
        1, PasswordChange(current_password=TEST_PASSWORD, password=NEW_PASSWORD), "owner-change"
    )
    assert auth.session(token) is None
    initialize_auth(database)
    token, _ = auth.login("owner", NEW_PASSWORD, None, "owner-new-password")
    assert auth.session(token)["user_id"] == 1


def test_profile_requires_password_and_resets_changed_contact_verification(database):
    alice = member(database)
    with database.connection() as connection, connection:
        connection.execute(
            "UPDATE users SET email_verified_at='test',phone_verified_at='test',"
            "email_notifications=1,sms_notifications=1,monthly_reports=1 WHERE id=?",
            (alice["id"],),
        )
    service = UserAccountService(database)
    payload = ProfileUpdate(
        display_name="Alice Updated", email="new@example.com", phone="+381641111111", current_password="wrong"
    )
    with pytest.raises(HTTPException) as error:
        service.update_profile(alice["id"], payload, "bad-profile")
    assert error.value.status_code == 400
    from pydantic import SecretStr

    payload.current_password = SecretStr(PASSWORD)
    profile = service.update_profile(alice["id"], payload, "good-profile")
    assert profile["display_name"] == "Alice Updated" and profile["email_verified_at"] is None
    assert profile["phone_verified_at"] is None
    with database.connection() as connection:
        row = connection.execute("SELECT * FROM users WHERE id=?", (alice["id"],)).fetchone()
        assert row["email_notifications"] == row["sms_notifications"] == row["monthly_reports"] == 0


def test_disable_enable_does_not_resurrect_sessions_or_recovery_links(database):
    member(database)
    auth = AuthService(database)
    token, _ = auth.login("alice", PASSWORD, None, "before-disable")
    service = UserAccountService(database)
    reset = service.issue_code("reset", "alice")
    service.set_active("alice", False)
    assert auth.session(token) is None
    with pytest.raises(HTTPException):
        auth.login("alice", PASSWORD, None, "disabled")
    service.set_active("alice", True)
    assert auth.session(token) is None
    with pytest.raises(HTTPException):
        service.reset_password(PasswordReset(token=reset, password=NEW_PASSWORD), "old-recovery")
    with pytest.raises(Conflict):
        service.set_active("owner", False)


def test_account_limit_spans_sources_and_email_aliases(database, monkeypatch):
    from app.services import auth_service

    member(database)
    monkeypatch.setattr(auth_service, "verify_password", lambda *_args: False)
    auth = AuthService(database)
    for index in range(30):
        with pytest.raises(HTTPException) as error:
            auth.login("alice" if index % 2 else "alice@example.com", "wrong", None, "source:" + str(index))
        assert error.value.status_code == 401
    with pytest.raises(HTTPException) as error:
        auth.login("alice", "wrong", None, "fresh-source")
    assert error.value.status_code == 429
    assert int(error.value.headers["Retry-After"]) <= 60


def test_audit_is_bounded_and_contains_no_contacts_or_credentials(database):
    from app.services.auth_service import security_event

    member(database)
    with database.operational_transaction() as connection:
        for index in range(10005):
            connection.execute(
                "INSERT INTO auth_security_events VALUES (?,NULL,'synthetic',?)",
                (str(index), int(time.time())),
            )
        security_event(connection, None, "synthetic")
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM auth_security_events").fetchone()[0] <= 10000
        fields = str([dict(row) for row in connection.execute("SELECT * FROM auth_security_events LIMIT 5")])
        assert PASSWORD not in fields and "@example.com" not in fields


def test_legacy_owner_sessions_are_revoked_during_operational_schema_upgrade(database):
    from app.services.auth_service import owner_key

    with database.connection() as connection, connection:
        connection.execute("DROP TABLE auth_sessions")
        connection.execute(
            "CREATE TABLE auth_sessions(token_hash TEXT PRIMARY KEY,csrf TEXT NOT NULL,"
            "owner_key TEXT NOT NULL,expires_at BIGINT NOT NULL,last_seen BIGINT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO auth_sessions VALUES (?,?,?,?,?)",
            (
                token_hash("legacy-cookie"),
                "legacy-csrf",
                owner_key(),
                int(time.time()) + 3600,
                int(time.time()),
            ),
        )
    initialize_auth(database)
    assert AuthService(database).session("legacy-cookie") is None
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] == 0
    from .conftest import TEST_PASSWORD

    token, _ = AuthService(database).login("owner", TEST_PASSWORD, None, "upgraded")
    assert AuthService(database).session(token)["user_id"] == 1


def test_environment_owner_reset_does_not_reset_member_passwords_or_sessions(database, monkeypatch):
    from app.core.config import settings
    from app.services.auth_service import hash_password
    from pydantic import SecretStr

    from .conftest import TEST_PASSWORD

    member(database)
    auth = AuthService(database)
    old, _ = auth.login("owner", TEST_PASSWORD, None, "old-owner")
    member_token, _ = auth.login("alice", PASSWORD, None, "member")
    monkeypatch.setattr(settings, "owner_password_hash", SecretStr(hash_password(NEW_PASSWORD)))
    assert auth.session(old) is None
    with pytest.raises(HTTPException):
        auth.login("owner", TEST_PASSWORD, None, "before-restart")
    initialize_auth(database)
    assert auth.session(member_token) is not None
    token, _ = auth.login("owner", NEW_PASSWORD, None, "new-owner")
    assert auth.session(token)["is_admin"] == 1


@pytest.mark.parametrize("function", ["hash_password", "verify_password"])
def test_password_work_uses_shared_bounded_hash_slots(database, monkeypatch, function):
    from threading import BoundedSemaphore

    from app.services import auth_service

    monkeypatch.setattr(auth_service, "HASH_SLOTS", BoundedSemaphore(0))
    with pytest.raises(HTTPException) as error:
        if function == "hash_password":
            auth_service.hash_password(PASSWORD)
        else:
            auth_service.verify_password(None, PASSWORD)
    assert error.value.status_code == 429


def test_links_are_replaced_not_reused_and_invalid_targets_are_controlled(database):
    service = UserAccountService(database)
    member(database)
    first = service.issue_code("reset", "alice")
    second = service.issue_code("reset", "ALICE")
    assert first != second
    with pytest.raises(HTTPException):
        service.reset_password(PasswordReset(token=first, password=NEW_PASSWORD), "replaced")
    service.reset_password(PasswordReset(token=second, password=NEW_PASSWORD), "current")
    with pytest.raises(ValueError):
        service.issue_code("invite", "alice@example.com")
    with pytest.raises(NotFound):
        service.issue_code("reset", "nobody")
    with pytest.raises(NotFound):
        service.set_active("nobody", False)
    with pytest.raises(NotFound):
        service.profile(999)
    with pytest.raises(ValueError):
        service.issue_code("other", "nobody")


def test_login_rechecks_deactivation_after_password_verification(database, monkeypatch):
    from app.services import auth_service

    member(database)
    original = auth_service.verify_password

    def deactivate(encoded, password):
        result = original(encoded, password)
        UserAccountService(database).set_active("alice", False)
        return result

    monkeypatch.setattr(auth_service, "verify_password", deactivate)
    with pytest.raises(HTTPException) as error:
        AuthService(database).login("alice", PASSWORD, None, "racing-login")
    assert error.value.status_code == 401
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM auth_sessions WHERE user_id<>1").fetchone()[0] == 0


def test_registration_account_failure_rolls_back_credentials_and_can_retry(database, monkeypatch):
    from contextlib import contextmanager

    service = UserAccountService(database)
    payload = registration()
    original = database.operational_transaction

    class FailAccount:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params=()):
            if "INSERT INTO accounts" in sql:
                raise RuntimeError("synthetic account setup failure")
            return self.connection.execute(sql, params)

    @contextmanager
    def failing():
        with original() as connection:
            yield FailAccount(connection)

    with monkeypatch.context() as patch:
        patch.setattr(database, "operational_transaction", failing)
        with pytest.raises(RuntimeError, match="account setup"):
            service.register(payload, "account-failure")
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM auth_codes").fetchone()[0] == 0
    assert service.register(payload, "account-retry")["username"] == "alice"


def test_trusted_restore_revocation_invalidates_all_users_and_links(database):
    member(database)
    member(database, "bob")
    auth = AuthService(database)
    alice, _ = auth.login("alice", PASSWORD, None, "alice")
    bob, _ = auth.login("bob", PASSWORD, None, "bob")
    service = UserAccountService(database)
    service.issue_code("reset", "alice")
    service.issue_code("reset", "bob")
    service.revoke_all()
    assert auth.session(alice) is None and auth.session(bob) is None
    with database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM auth_codes").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 3
    new, _ = auth.login("alice", PASSWORD, None, "after-restore-revocation")
    assert auth.session(new) is not None


def test_hashing_rejects_invalid_unicode_without_consuming_hash_capacity(database, monkeypatch):
    from types import SimpleNamespace

    from app.services import auth_service

    monkeypatch.setattr(
        auth_service,
        "PASSWORDS",
        SimpleNamespace(hash=lambda _value: pytest.fail("Invalid Unicode must not be hashed")),
    )
    with pytest.raises(HTTPException) as error:
        auth_service.hash_password("a" * 15 + "\ud800")
    assert error.value.status_code == 422


def test_compromised_account_can_be_recovered_without_reenabling_old_credentials(database):
    member(database)
    service = UserAccountService(database)
    service.set_active("alice", False)
    token = service.issue_code("reset", "alice")
    service.reset_password(PasswordReset(token=token, password=NEW_PASSWORD), "disabled-recovery")
    auth = AuthService(database)
    with pytest.raises(HTTPException):
        auth.login("alice", NEW_PASSWORD, None, "still-disabled")
    service.set_active("alice", True)
    with pytest.raises(HTTPException):
        auth.login("alice", PASSWORD, None, "old-credential")
    new, _ = auth.login("alice", NEW_PASSWORD, None, "recovered")
    assert auth.session(new) is not None

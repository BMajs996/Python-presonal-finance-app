import sys
from urllib.parse import parse_qs, urlsplit

import pytest
from app import manage_users
from app.database import FinanceDatabase
from app.services.auth_service import initialize_auth, token_hash


def test_cli_invite_prints_single_use_fragment_and_closes_database(tmp_path, monkeypatch, capsys):
    database = FinanceDatabase(tmp_path / "cli.db")
    initialize_auth(database)
    monkeypatch.setattr(manage_users, "open_database", lambda _settings: database)
    monkeypatch.setattr(sys, "argv", ["manage_users", "invite", "alice@example.com"])
    manage_users.main()
    output = capsys.readouterr().out
    link = output.splitlines()[-1]
    parts = urlsplit(link)
    assert parts.path == "/register" and not parts.query
    token = parse_qs(parts.fragment)["token"][0]
    reopened = FinanceDatabase(tmp_path / "cli.db")
    try:
        row = reopened.conn.execute("SELECT token_hash FROM auth_codes").fetchone()
        assert row[0] == token_hash(token)
        assert row[0] not in output
    finally:
        reopened.close()


@pytest.mark.parametrize("arguments", [["invite"], ["reset"], ["invite", "not-email"]])
def test_cli_invalid_arguments_do_not_open_database(monkeypatch, arguments):
    monkeypatch.setattr(sys, "argv", ["manage_users", *arguments])
    monkeypatch.setattr(manage_users, "open_database", lambda _settings: pytest.fail("Must not open DB"))
    with pytest.raises(SystemExit) as error:
        manage_users.main()
    assert error.value.code == 2


def test_cli_list_omits_contacts_and_passwords(tmp_path, monkeypatch, capsys):
    database = FinanceDatabase(tmp_path / "list.db")
    initialize_auth(database)
    monkeypatch.setattr(manage_users, "open_database", lambda _settings: database)
    monkeypatch.setattr(sys, "argv", ["manage_users", "list"])
    manage_users.main()
    output = capsys.readouterr().out
    assert "owner" in output and "admin=1" in output
    assert "$argon2" not in output


@pytest.mark.parametrize("action,target", [("disable", "alice"), ("enable", "alice"), ("revoke-all", None)])
def test_cli_administration_dispatches_without_printing_contacts(monkeypatch, capsys, action, target):
    from unittest.mock import Mock

    database = Mock()
    service = Mock()
    monkeypatch.setattr(manage_users, "open_database", lambda _settings: database)
    monkeypatch.setattr(manage_users, "initialize_auth", lambda _database: None)
    monkeypatch.setattr(manage_users, "UserAccountService", lambda _database: service)
    monkeypatch.setattr(sys, "argv", ["manage_users", action, *([target] if target else [])])
    manage_users.main()
    if action == "revoke-all":
        service.revoke_all.assert_called_once_with()
    else:
        service.set_active.assert_called_once_with("alice", action == "enable")
    database.close.assert_called_once()
    assert "@" not in capsys.readouterr().out

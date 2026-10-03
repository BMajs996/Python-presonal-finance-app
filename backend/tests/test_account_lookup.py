from datetime import date

from app.schemas import AccountCreate, TransactionCreate, TransferCreate


def test_single_account_lookup_preserves_balance_and_inactive_access(db):
    source = db.add_account(AccountCreate(name="Source", opening_balance="100.25"))
    target = db.add_account(AccountCreate(name="Target", opening_balance="10.00"))
    db.add_transaction(
        TransactionCreate(
            date=date(2026, 1, 1),
            type="expense",
            category="Food",
            amount="2.15",
            account_id=target["id"],
        )
    )
    db.add_transfer(
        TransferCreate(
            date=date(2026, 1, 1),
            from_account_id=source["id"],
            to_account_id=target["id"],
            amount="20.00",
        )
    )
    expected = next(account for account in db.list_accounts() if account["id"] == target["id"])
    assert expected["balance"] == 27.85
    assert db.get_account(target["id"]) == expected
    db.deactivate_account(target["id"])
    assert target["id"] not in {account["id"] for account in db.list_accounts()}
    assert db.get_account(target["id"]) == {**expected, "active": 0}
    assert db.get_account(999999) is None


def test_lookup_does_not_convert_unrelated_accounts(db, monkeypatch):
    target = db.add_account(AccountCreate(name="Target"))
    db.add_account(AccountCreate(name="Unrelated"))
    converted_ids = []
    convert = db.accounts._to_domain

    def record_conversion(row):
        converted_ids.append(row["id"])
        return convert(row)

    monkeypatch.setattr(db.accounts, "_to_domain", record_conversion)
    assert db.get_account(target["id"])["id"] == target["id"]
    assert converted_ids == [target["id"]]

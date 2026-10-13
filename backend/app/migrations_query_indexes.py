"""Portable indexes for bounded ledger reads and due-schedule selection."""

INDEXES = {
    "idx_transactions_live_date_id": "ON transactions(date DESC,id DESC) WHERE deleted_at IS NULL",
    "idx_transactions_live_account_date_id": "ON transactions(account_id,date DESC,id DESC) "
    "WHERE deleted_at IS NULL",
    "idx_transactions_expense_category_date": "ON transactions(category,date) "
    "WHERE deleted_at IS NULL AND type='expense'",
    "idx_transfers_from_date": "ON transfers(from_account_id,date)",
    "idx_transfers_to_date": "ON transfers(to_account_id,date)",
    "idx_recurring_due": "ON recurring_transactions(next_date,id) WHERE active=1",
}


def migrate_query_indexes(connection, _base_currency="USD"):
    for name, definition in INDEXES.items():
        # Names and definitions are fixed migration metadata, never request input.
        connection.execute(f"CREATE INDEX {name} {definition}")

from datetime import date

from app.schemas import TransactionCreate


def test_recent_matches_paginated_items_without_count_query(db):
    for day in range(1, 12):
        db.add_transaction(
            TransactionCreate(date=date(2026, 1, day), type="income", category="Salary", amount=day)
        )
    deleted = db.list_transactions(limit=1)[0][0]
    db.delete_transaction(deleted["id"])
    expected, total = db.list_transactions(limit=8)
    assert total == 10
    queries = []
    db.conn.set_trace_callback(queries.append)
    try:
        assert db.transactions.recent() == expected
    finally:
        db.conn.set_trace_callback(None)
    assert len(queries) == 1
    assert "COUNT(" not in queries[0].upper()

from .base_repository import BaseRepository


class TransactionRepository(BaseRepository):
    def list(
        self,
        search: str = "",
        category: str = "",
        type_: str = "",
        account_id: int | None = None,
        date_start: str = "",
        date_end: str = "",
        limit: int = 100,
        offset: int = 0,
    ):
        query = """
            SELECT t.*, a.name AS account_name
            FROM transactions t
            LEFT JOIN accounts a ON a.id=t.account_id
            WHERE 1=1
        """
        params = []
        if search:
            query += " AND (t.description LIKE ? OR t.category LIKE ? OR a.name LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        if category:
            query += " AND t.category=?"
            params.append(category)
        if type_:
            query += " AND t.type=?"
            params.append(type_)
        if account_id is not None:
            query += " AND t.account_id=?"
            params.append(account_id)
        if date_start:
            query += " AND t.date>=?"
            params.append(date_start)
        if date_end:
            query += " AND t.date<=?"
            params.append(date_end)

        total = self.conn.execute(f"SELECT COUNT(*) FROM ({query})", params).fetchone()[0]
        query += " ORDER BY t.date DESC, t.id DESC LIMIT ? OFFSET ?"
        rows = self.conn.execute(query, [*params, limit, offset]).fetchall()
        return [dict(row) for row in rows], total

    def get(self, transaction_id: int):
        row = self.conn.execute(
            """
            SELECT t.*, a.name AS account_name
            FROM transactions t
            LEFT JOIN accounts a ON a.id=t.account_id
            WHERE t.id=?
            """,
            (transaction_id,),
        ).fetchone()
        return dict(row) if row else None

    def add(self, payload):
        account_id = self.resolve_account_id(payload.account_id)
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO transactions(date, type, category, amount, description, account_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.date.isoformat(),
                    payload.type,
                    payload.category.strip(),
                    payload.amount,
                    payload.description.strip(),
                    account_id,
                ),
            )
        return self.get(cursor.lastrowid)

    def update(self, transaction_id: int, payload):
        existing = self.get(transaction_id)
        if not existing:
            return None
        account_id = (
            self.resolve_account_id(payload.account_id)
            if payload.account_id is not None
            else existing["account_id"]
        )
        with self.conn:
            self.conn.execute(
                """
                UPDATE transactions
                SET date=?, type=?, category=?, amount=?, description=?, account_id=?
                WHERE id=?
                """,
                (
                    payload.date.isoformat(),
                    payload.type,
                    payload.category.strip(),
                    payload.amount,
                    payload.description.strip(),
                    account_id,
                    transaction_id,
                ),
            )
        return self.get(transaction_id)

    def delete(self, transaction_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))

    def categories(self):
        return [
            row["category"]
            for row in self.conn.execute(
                "SELECT DISTINCT category FROM transactions ORDER BY category"
            )
        ]

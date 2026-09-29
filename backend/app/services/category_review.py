"""Inventory canonical-key collisions without rewriting category identity."""

import unicodedata
from pathlib import Path

from ..domain.category import CANONICAL_POLICY, canonical_key
from .read_only_database import read_only_database


def _usage_order(row: dict) -> tuple[str, str, str, str]:
    return row["source"], row["currency"] or "", row["kind"], row["state"]


def review_categories(path: Path, url: str | None = None, limit: int = 100, offset: int = 0):
    if not 1 <= limit <= 1000 or offset < 0:
        raise ValueError("Review requires limit 1-1000 and a non-negative offset")
    with read_only_database(path, url) as conn:
        rows = conn.execute("""
            SELECT 'transaction' AS source, t.category, a.currency, t.type AS kind,
                   CASE WHEN t.deleted_at IS NULL THEN 'posted-or-future' ELSE 'deleted' END AS state,
                   COUNT(*) AS row_count, SUM(t.amount_cents) AS cents
            FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
            GROUP BY t.category,a.currency,t.type,(t.deleted_at IS NULL)
            UNION ALL
            SELECT 'recurring', r.category, a.currency, r.type,
                   CASE WHEN r.active=1 THEN 'active' ELSE 'inactive' END,
                   COUNT(*), SUM(r.amount_cents)
            FROM recurring_transactions r LEFT JOIN accounts a ON a.id=r.account_id
            GROUP BY r.category,a.currency,r.type,r.active
            UNION ALL
            SELECT 'budget', b.category, a.currency, 'limit', b.month_year,
                   COUNT(*), SUM(b.monthly_limit_cents)
            FROM budgets b LEFT JOIN accounts a ON a.name='Main Account'
            GROUP BY b.category,a.currency,b.month_year
        """).fetchall()
    groups: dict[str, dict[str, list[dict]]] = {}
    baseline: dict[tuple[str, str | None, str, str], dict[str, int]] = {}
    for row in rows:
        name = row["category"]
        group = groups.setdefault(canonical_key(name), {})
        usage = {
            "source": row["source"],
            "currency": row["currency"],
            "kind": row["kind"],
            "state": row["state"],
            "row_count": row["row_count"],
            "amount_cents": str(row["cents"]),
        }
        group.setdefault(name, []).append(usage)
        key = (row["source"], row["currency"], row["kind"], row["state"])
        total = baseline.setdefault(key, {"row_count": 0, "amount_cents": 0})
        total["row_count"] += row["row_count"]
        total["amount_cents"] += int(row["cents"])
    collisions: list[dict] = []
    for candidate_key, variants in sorted(groups.items()):
        if len(variants) <= 1 and candidate_key:
            continue
        variant_rows: list[dict] = []
        for display_name, usage_rows in sorted(variants.items()):
            variant_rows.append(
                {
                    "display_name": display_name,
                    "usage": sorted(usage_rows, key=_usage_order),
                }
            )
        collisions.append({"canonical_key": candidate_key, "variants": variant_rows})
    return {
        "policy": CANONICAL_POLICY,
        "unicode_version": unicodedata.unidata_version,
        "identity": "exact-text",
        "distinct_names": sum(len(group) for group in groups.values()),
        "total_collisions": len(collisions),
        "items": collisions[offset : offset + limit],
        "baseline": [
            {
                "source": key[0],
                "currency": key[1],
                "kind": key[2],
                "state": key[3],
                "row_count": value["row_count"],
                "amount_cents": str(value["amount_cents"]),
            }
            for key, value in sorted(baseline.items(), key=lambda item: tuple(str(part) for part in item[0]))
        ],
    }

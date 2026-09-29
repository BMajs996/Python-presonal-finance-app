"""Category identity remains exact text until an owner-reviewed ID migration."""

import unicodedata

CANONICAL_POLICY = "nfc-whitespace-casefold-v1"


def clean_category(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Category is required")
    return value


def canonical_key(value: str) -> str:
    """Candidate identity for collision review only, never an automatic merge."""
    value = " ".join(unicodedata.normalize("NFC", value).split())
    return unicodedata.normalize("NFC", value.casefold())

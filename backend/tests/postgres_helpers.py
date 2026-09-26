import os
from contextlib import contextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql


@contextmanager
def temporary_schema(url):
    parts = urlsplit(url)
    if not parts.path.endswith("_test"):
        raise ValueError("Test PostgreSQL URL must name an isolated database ending in _test")
    schema = "test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    options = [(key, value) for key, value in parse_qsl(parts.query) if key != "options"]
    options.append(("options", "-csearch_path=" + schema))
    # Preserve an empty host for Unix-socket peer authentication.
    isolated = f"{parts.scheme}://{parts.netloc}{parts.path}?{urlencode(options)}"
    try:
        yield isolated
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def pg_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    with temporary_schema(url) as isolated:
        yield isolated

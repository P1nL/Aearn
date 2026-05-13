from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from app.core.config import get_settings


@contextmanager
def connect() -> Iterator[Connection[dict[str, object]]]:
    conn = psycopg.connect(
        get_settings().database_url,
        connect_timeout=10,
        row_factory=dict_row,
    )
    try:
        yield conn
    finally:
        conn.close()

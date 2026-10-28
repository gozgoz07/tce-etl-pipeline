"""Database connection and execution utilities for TCE."""

import logging
from contextlib import contextmanager
from typing import Generator, Optional

import psycopg

from tce.settings import settings

logger = logging.getLogger(__name__)


@contextmanager
def get_connection(
    database_url: Optional[str] = None,
) -> Generator[psycopg.Connection, None, None]:
    """Provide a single PostgreSQL connection using psycopg 3.

    Opens exactly one connection and closes it upon exit.
    Logs no credentials or URLs.
    """
    url = database_url or settings.get_database_url()
    logger.debug("Connecting to PostgreSQL...")
    conn = psycopg.connect(url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        logger.debug("PostgreSQL connection closed.")


def init_db(database_url: Optional[str] = None) -> None:
    """Initialize database tables using sql/001_init.sql."""
    init_sql_path = settings.SQL_DIR / "001_init.sql"
    if not init_sql_path.exists():
        raise FileNotFoundError(f"Schema file not found at {init_sql_path}")

    sql_content = init_sql_path.read_text(encoding="utf-8")
    with get_connection(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_content)
    logger.info("Database schema initialized successfully.")

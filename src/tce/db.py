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
    """Initialize database schema and apply migrations from sql/*.sql in order."""
    if not settings.SQL_DIR.exists():
        raise FileNotFoundError(f"SQL directory not found at {settings.SQL_DIR}")

    sql_files = sorted(settings.SQL_DIR.glob("*.sql"))
    if not sql_files:
        raise FileNotFoundError(f"No SQL files found in {settings.SQL_DIR}")

    with get_connection(database_url) as conn:
        with conn.cursor() as cur:
            for sql_file in sql_files:
                logger.info("Applying SQL migration: %s", sql_file.name)
                content = sql_file.read_text(encoding="utf-8")
                cur.execute(content)
    logger.info("Database schema and migrations initialized successfully.")

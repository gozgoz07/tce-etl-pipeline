"""Tests for database initialization and connection management."""

from unittest.mock import MagicMock, patch

import pytest

from tce.db import get_connection, init_db
from tce.settings import settings


def test_init_db_mock():
    """Verify that init_db reads 001_init.sql and executes it on the connection."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("tce.db.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        # Call once: executes all SQL migration files (001_init.sql, 002_add_hf_source.sql)
        init_db("postgresql://dummy:dummy@localhost/dummy")
        num_sql_files = len(list(settings.SQL_DIR.glob("*.sql")))
        assert mock_cursor.execute.call_count == num_sql_files
        all_executed_sql = " ".join(call[0][0] for call in mock_cursor.execute.call_args_list)
        assert "CREATE TABLE IF NOT EXISTS entities" in all_executed_sql
        assert "CREATE TABLE IF NOT EXISTS items" in all_executed_sql
        assert "CREATE TABLE IF NOT EXISTS topics" in all_executed_sql
        assert "CREATE TABLE IF NOT EXISTS item_topics" in all_executed_sql
        assert "CREATE TABLE IF NOT EXISTS topic_snapshots" in all_executed_sql
        assert "CREATE TABLE IF NOT EXISTS scopes" in all_executed_sql

        # Call second time (idempotence verification)
        init_db("postgresql://dummy:dummy@localhost/dummy")
        assert mock_cursor.execute.call_count == num_sql_files * 2


def test_get_connection_rollback_on_error():
    """Verify that get_connection rolls back transaction when an exception occurs."""
    mock_conn = MagicMock()
    with patch("psycopg.connect", return_value=mock_conn):
        with pytest.raises(RuntimeError):
            with get_connection("postgresql://dummy:dummy@localhost/dummy"):
                raise RuntimeError("Boom")

        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()


@pytest.mark.skipif(
    not settings.TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not set",
)
def test_real_db_init_twice():
    """Execute init_db twice on real database if TEST_DATABASE_URL is available."""
    init_db(settings.TEST_DATABASE_URL)
    init_db(settings.TEST_DATABASE_URL)

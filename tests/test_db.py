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

        # Call once
        init_db("postgresql://dummy:dummy@localhost/dummy")
        assert mock_cursor.execute.call_count == 1
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS entities" in executed_sql
        assert "CREATE TABLE IF NOT EXISTS items" in executed_sql
        assert "CREATE TABLE IF NOT EXISTS topics" in executed_sql
        assert "CREATE TABLE IF NOT EXISTS item_topics" in executed_sql
        assert "CREATE TABLE IF NOT EXISTS topic_snapshots" in executed_sql
        assert "CREATE TABLE IF NOT EXISTS scopes" in executed_sql

        # Call second time (idempotence verification)
        init_db("postgresql://dummy:dummy@localhost/dummy")
        assert mock_cursor.execute.call_count == 2


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

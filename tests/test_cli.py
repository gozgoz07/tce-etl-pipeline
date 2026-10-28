"""Basic tests for CLI interface."""

from typer.testing import CliRunner

from tce.cli import app

runner = CliRunner()


def test_cli_help():
    """Verify that tce --help runs and displays command list."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Trending Content Engine (TCE) CLI" in result.stdout
    assert "collect" in result.stdout
    assert "seed" in result.stdout
    assert "attach" in result.stdout
    assert "snapshot" in result.stdout
    assert "report" in result.stdout
    assert "run-all" in result.stdout

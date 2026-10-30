"""CLI entry point for TCE using Typer."""

import logging
from typing import Optional

import typer

from tce.settings import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("tce")

app = typer.Typer(
    name="tce",
    help="Trending Content Engine (TCE) CLI",
    no_args_is_help=True,
)

db_app = typer.Typer(help="Database operations")
app.add_typer(db_app, name="db")


@db_app.command("init")
def db_init() -> None:
    """Initialize database tables using sql/001_init.sql."""
    from tce.db import init_db

    try:
        init_db()
        typer.echo("Database schema initialized successfully.")
    except Exception as e:
        logger.error("Failed to initialize database schema: %s", e)
        raise typer.Exit(code=1) from e


@app.command("seed")
def seed() -> None:
    """Load entities.yaml and topics.yaml into database."""
    from tce.db import get_connection
    from tce.seed import seed_all

    try:
        with get_connection() as conn:
            num_e, num_t = seed_all(conn)
        typer.echo(f"Successfully seeded {num_e} entities and {num_t} topics.")
    except Exception as e:
        logger.error("Failed to seed database: %s", e)
        raise typer.Exit(code=1) from e


@app.command("collect")
def collect(
    source: str = typer.Option(
        "all",
        "--source",
        "-s",
        help="Source to collect: hn, arxiv, rss, hf, or all",
    ),
) -> None:
    """Collect, enrich, and store items from sources."""
    from tce.collectors.service import collect_and_store
    from tce.db import get_connection

    try:
        with get_connection() as conn:
            seen, new_count, updated, had_errors = collect_and_store(conn, source=source)
        typer.echo(
            f"Collection finished: {seen} seen, {new_count} new, {updated} updated."
        )
        if had_errors:
            raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as e:
        logger.error("Collection failed: %s", e)
        raise typer.Exit(code=1) from e


@app.command("enrich")
def enrich(
    since_days: int = typer.Option(
        7,
        "--since-days",
        help="Number of days in the past to re-enrich items",
    ),
) -> None:
    """Recalculate keywords and entity_ids for recent items."""
    from tce.db import get_connection
    from tce.enrich.pipeline import re_enrich_items

    try:
        with get_connection() as conn:
            count = re_enrich_items(conn, since_days=since_days)
        typer.echo(f"Successfully re-enriched {count} items.")
    except Exception as e:
        logger.error("Failed to re-enrich items: %s", e)
        raise typer.Exit(code=1) from e


@app.command("attach")
def attach(
    since_days: int = typer.Option(
        7,
        "--since-days",
        help="Number of days in the past to attach items to topics",
    ),
) -> None:
    """Attach recent items to matching topics."""
    from tce.db import get_connection
    from tce.topics import attach_items_to_topics

    try:
        with get_connection() as conn:
            count = attach_items_to_topics(conn, since_days=since_days)
        typer.echo(f"Successfully attached {count} item-topic relationships.")
    except Exception as e:
        logger.error("Failed to attach items to topics: %s", e)
        raise typer.Exit(code=1) from e


@app.command("snapshot")
def snapshot(
    date: Optional[str] = typer.Option(
        None,
        "--date",
        help="Snapshot date in YYYY-MM-DD format (defaults to yesterday UTC)",
    ),
) -> None:
    """Compute daily snapshot and velocity score per topic."""
    from datetime import datetime

    from tce.db import get_connection
    from tce.snapshots import generate_snapshots

    target_date = None
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError as e:
            typer.echo(f"Invalid date format: {date}. Expected YYYY-MM-DD.")
            raise typer.Exit(code=1) from e

    try:
        with get_connection() as conn:
            count = generate_snapshots(conn, target_date=target_date)
        typer.echo(f"Successfully generated {count} topic snapshots.")
    except Exception as e:
        logger.error("Failed to generate snapshots: %s", e)
        raise typer.Exit(code=1) from e


@app.command("report")
def report(
    date: Optional[str] = typer.Option(
        None,
        "--date",
        help="Report date in YYYY-MM-DD format (defaults to yesterday UTC)",
    ),
) -> None:
    """Display top 10 topics ranked by velocity score."""
    from datetime import datetime

    from tabulate import tabulate

    from tce.db import get_connection
    from tce.snapshots import get_top_topics_report

    target_date = None
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError as e:
            typer.echo(f"Invalid date format: {date}. Expected YYYY-MM-DD.")
            raise typer.Exit(code=1) from e

    try:
        with get_connection() as conn:
            results = get_top_topics_report(conn, target_date=target_date, limit=10)

        if not results:
            typer.echo(f"No snapshot data available for date {target_date or 'yesterday'}.")
            return

        table_data = []
        for r in results:
            table_data.append([
                r["name"],
                f"{r['velocity_score']:.3f}",
                r["c24"],
                f"{r['baseline7']:.3f}",
                r["distinct_sources"],
                r["engagement_sum"],
            ])

        headers = ["Topic", "Velocity", "c24", "Baseline7", "Distinct Sources", "Engagement"]
        typer.echo("\n" + tabulate(table_data, headers=headers, tablefmt="github") + "\n")
    except Exception as e:
        logger.error("Failed to generate report: %s", e)
        raise typer.Exit(code=1) from e


@app.command("run-all")
def run_all() -> None:
    """Run full pipeline: collect --source all, attach --since-days 7, snapshot."""
    import time

    from tce.collectors.service import collect_and_store
    from tce.db import get_connection
    from tce.snapshots import generate_snapshots
    from tce.topics import attach_items_to_topics

    start_time = time.time()
    had_errors = False
    typer.echo("Starting full pipeline run-all...")

    try:
        with get_connection() as conn:
            # Step 1: Collect all
            try:
                typer.echo("[1/3] Collecting items from all sources...")
                seen, new_count, updated, coll_err = collect_and_store(conn, source="all")
                typer.echo(f"      Finished: {seen} seen, {new_count} new, {updated} updated.")
                if coll_err:
                    had_errors = True
            except Exception as e:
                logger.error("Step 1 (collect) failed: %s", e)
                had_errors = True

            # Step 2: Attach
            try:
                typer.echo("[2/3] Attaching items to topics (since_days=7)...")
                attach_count = attach_items_to_topics(conn, since_days=7)
                typer.echo(f"      Attached {attach_count} item-topic relationships.")
            except Exception as e:
                logger.error("Step 2 (attach) failed: %s", e)
                had_errors = True

            # Step 3: Snapshot
            try:
                typer.echo("[3/3] Generating daily topic snapshots...")
                snap_count = generate_snapshots(conn)
                typer.echo(f"      Generated {snap_count} topic snapshots.")
            except Exception as e:
                logger.error("Step 3 (snapshot) failed: %s", e)
                had_errors = True
    except Exception as e:
        logger.error("Database connection failed in run-all: %s", e)
        had_errors = True

    duration = time.time() - start_time
    typer.echo(f"Pipeline run-all completed in {duration:.2f} seconds.")

    if had_errors:
        typer.echo("Pipeline completed with errors.")
        raise typer.Exit(code=1)
    else:
        typer.echo("Pipeline completed successfully.")


if __name__ == "__main__":
    app()

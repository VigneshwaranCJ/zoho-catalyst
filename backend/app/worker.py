"""Background worker entrypoint.

Phase 2: a heartbeat loop that proves the container runs and can reach the DB.
Phase 3+: claims jobs from PostgreSQL with `SELECT ... FOR UPDATE SKIP LOCKED`
(ingestion, re-indexing, ticket sync, weekly report). See TECHNOLOGY_SELECTION §3.16.

Run: uv run python -m app.worker
"""

import asyncio
import signal

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, get_engine
from app.utils.event_loop import run

log = get_logger("worker")
HEARTBEAT_SECONDS = 30


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: Ctrl+C still raises KeyboardInterrupt
            pass

    log.info("worker_started")
    while not stop.is_set():
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            log.info("worker_heartbeat", jobs_pending=0)
        except Exception as exc:
            log.error("worker_db_unavailable", error=str(exc))
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_SECONDS)
        except TimeoutError:
            pass
    await dispose_engine()
    log.info("worker_stopped")


if __name__ == "__main__":
    run(main())

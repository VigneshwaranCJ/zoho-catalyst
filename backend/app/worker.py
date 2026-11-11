"""Background worker entrypoint.

Processes ingestion jobs one at a time (Docling is CPU-heavy; run more worker
containers to process more documents in parallel). Jobs are claimed from
PostgreSQL with `FOR UPDATE SKIP LOCKED`, so several workers cooperate safely.

Run: uv run python -m app.worker
"""

import asyncio
import os
import signal
import socket
import time

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine
from app.ingestion.extractor import DoclingExtractor
from app.ingestion.processor import IngestionProcessor
from app.utils.event_loop import run

log = get_logger("worker")
HEARTBEAT_SECONDS = 60


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: Ctrl+C still raises KeyboardInterrupt
            pass

    extractor = DoclingExtractor(
        artifacts_path=settings.docling_artifacts_path,
        document_timeout=settings.docling_document_timeout_seconds,
    )
    log.info("worker_starting", worker_id=worker_id)
    started = time.perf_counter()
    await asyncio.to_thread(extractor.warm_up)  # load models before taking jobs
    log.info("worker_ready", model_load_s=round(time.perf_counter() - started, 1))

    processor = IngestionProcessor(extractor=extractor)
    last_heartbeat = 0.0
    processed = 0
    while not stop.is_set():
        try:
            if await processor.run_once(worker_id):
                processed += 1
                continue  # more work may be waiting: don't sleep
        except Exception as exc:  # e.g. database briefly unavailable
            log.error("worker_loop_error", error=repr(exc))
        if time.perf_counter() - last_heartbeat > HEARTBEAT_SECONDS:
            log.info("worker_heartbeat", processed=processed)
            last_heartbeat = time.perf_counter()
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
        except TimeoutError:
            pass
    await dispose_engine()
    log.info("worker_stopped", processed=processed)


if __name__ == "__main__":
    run(main())

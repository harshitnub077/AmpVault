import asyncio
import logging
import signal

from src.core.config import get_settings
from src.core.database import async_session_factory
from src.webhooks.outbox import OutboxDispatcher

logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp":"%(asctime)s", "level":"%(levelname)s", "logger":"%(name)s", "message":"%(message)s"}',
)
logger = logging.getLogger("escrowatt.outbox_worker")


async def run_worker(poll_interval: float = 2.0, run_once: bool = False) -> None:
    settings = get_settings()
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            # Windows or non-main thread fallback
            pass

    logger.info("Outbox dispatcher worker started (poll_interval=%ss)", poll_interval)

    while not stop_event.is_set():
        try:
            async with async_session_factory() as session:
                dispatcher = OutboxDispatcher(session, webhook_secret=settings.GATEWAY_WEBHOOK_SECRET)
                dispatched = await dispatcher.dispatch_pending_events(limit=50)
                if dispatched > 0:
                    await session.commit()
                    logger.info("Dispatched %d pending outbox events", dispatched)
        except Exception as exc:
            logger.error("Error in outbox dispatcher poll loop: %s", exc, exc_info=True)

        if run_once:
            break

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
        except TimeoutError:
            pass

    logger.info("Outbox dispatcher worker stopped gracefully")


def main() -> None:
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker process terminated")


if __name__ == "__main__":
    main()

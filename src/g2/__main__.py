"""Entry point: python -m g2"""

from __future__ import annotations

import asyncio
import signal
import sys

from g2.app import Orchestrator
from g2.infrastructure.logger import logger


async def main() -> None:
    orchestrator = Orchestrator()

    # Handle graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler() -> None:
        logger.info("Received shutdown signal")
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await orchestrator.start()

        # Wait for shutdown signal
        await shutdown_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        await orchestrator.shutdown()


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()

"""Entry point: python -m g2"""

from __future__ import annotations

import asyncio
import signal
import sys
import threading
from pathlib import Path

from g2.infrastructure.config import STORE_DIR
from g2.infrastructure.logger import logger


async def main() -> None:
    from g2.app import Orchestrator

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


def run_auth() -> None:
    """Authenticate WhatsApp via neonize.

    Writes status files for the setup script to poll:
      store/qr-data.txt       — raw QR string (for qr-browser method)
      store/auth-status.txt   — final status: authenticated | already_authenticated | failed:<reason>
    """
    import argparse

    parser = argparse.ArgumentParser(description="WhatsApp authentication")
    parser.add_argument("--pairing-code", action="store_true", help="Use pairing code instead of QR")
    parser.add_argument("--phone", type=str, help="Phone number for pairing code (e.g. 14155551234)")
    args = parser.parse_args(sys.argv[2:])  # skip "auth" subcommand

    auth_dir = STORE_DIR / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    qr_data_file = STORE_DIR / "qr-data.txt"
    status_file = STORE_DIR / "auth-status.txt"

    # Clean status files from previous runs
    qr_data_file.unlink(missing_ok=True)
    status_file.unlink(missing_ok=True)

    try:
        from neonize.client import NewClient
        from neonize.events import ConnectedEv, LoggedOutEv, QREv, StreamErrorEv
    except ImportError:
        print("neonize not installed. Install with: pip install neonize", file=sys.stderr)
        status_file.write_text("failed:neonize_not_installed")
        sys.exit(1)

    db_path = str(auth_dir / "neonize.db")
    client = NewClient(db_path)

    def write_status(status: str) -> None:
        status_file.write_text(status)

    # Override default QR handler to write data for the setup script
    @client.event.qr
    def on_qr(_client: object, qr_bytes: bytes) -> None:
        qr_str = qr_bytes.decode("utf-8") if isinstance(qr_bytes, bytes) else str(qr_bytes)
        qr_data_file.write_text(qr_str)
        # Also print to terminal for qr-terminal method
        try:
            import segno
            segno.make_qr(qr_str).terminal(compact=True)
        except Exception:
            print(f"QR data: {qr_str}")

    @client.event(ConnectedEv)
    def on_connected(_client: object, _event: object) -> None:
        print("WhatsApp connected successfully!")
        write_status("authenticated")

    @client.event(LoggedOutEv)
    def on_logged_out(_client: object, _event: object) -> None:
        print("Logged out from WhatsApp", file=sys.stderr)
        write_status("failed:logged_out")

    @client.event(StreamErrorEv)
    def on_stream_error(_client: object, event: object) -> None:
        code = getattr(event, "Code", "unknown")
        print(f"Stream error: {code}", file=sys.stderr)
        write_status(f"failed:{code}")

    print("Connecting to WhatsApp...")

    if args.pairing_code:
        if not args.phone:
            print("--phone is required with --pairing-code", file=sys.stderr)
            write_status("failed:missing_phone")
            sys.exit(1)
        # PairPhone also blocks forever like connect()
        client.PairPhone(args.phone, show_push_notification=True)
    else:
        client.connect()


def run() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        run_auth()
        return

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()

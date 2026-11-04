#!/usr/bin/env python3
"""Tunnel supervisor for Ampvault.

Keeps a live cloudflared tunnel running, automatically detecting disconnections
or server-side deauthorizations and restarting the tunnel immediately.
Writes the active URL to scripts/LIVE_TUNNEL_URL.txt.
"""

import re
import signal
import subprocess
import time
from pathlib import Path

URL_FILE = Path(__file__).parent / "LIVE_TUNNEL_URL.txt"
CLOUDFLARED_BIN = "/opt/homebrew/bin/cloudflared"
PORT = 8000
URL_PATTERN = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


def main() -> None:
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        running = False
        print("\nStopping tunnel supervisor...", flush=True)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    print("Starting Ampvault Tunnel Supervisor...", flush=True)

    while running:
        cmd = [CLOUDFLARED_BIN, "tunnel", "--url", f"http://127.0.0.1:{PORT}"]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            print(f"Failed to launch cloudflared: {e}", flush=True)
            time.sleep(5)
            continue

        active_url = None
        consecutive_errors = 0

        try:
            for line in iter(proc.stdout.readline, ""):
                if not running:
                    break

                # Check for tunnel URL
                match = URL_PATTERN.search(line)
                if match:
                    active_url = match.group(0)
                    URL_FILE.write_text(active_url.strip() + "\n", encoding="utf-8")
                    print(f"\n[TUNNEL ONLINE] Active URL: {active_url}\n", flush=True)
                    consecutive_errors = 0

                # Detect unrecoverable tunnel disconnects
                if "Unauthorized: Tunnel not found" in line or "Register tunnel error" in line:
                    consecutive_errors += 1
                    if consecutive_errors >= 2:
                        print("\n[TUNNEL ERROR] Server deauthorized tunnel. Restarting fresh connection...", flush=True)
                        break

                if "Failed to serve quic connection" in line:
                    consecutive_errors += 1
                    if consecutive_errors >= 5:
                        print("\n[TUNNEL STALL] Multiple QUIC connection failures. Restarting...", flush=True)
                        break

        except Exception as e:
            print(f"Exception during stream read: {e}", flush=True)

        # Terminate current process
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

        if running:
            print("Restarting tunnel in 2 seconds...", flush=True)
            time.sleep(2)

    if URL_FILE.exists():
        URL_FILE.unlink(missing_ok=True)
    print("Tunnel supervisor stopped.", flush=True)


if __name__ == "__main__":
    main()

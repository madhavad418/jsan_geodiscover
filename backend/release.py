"""Deployment entrypoint: wait for the database, migrate, seed, then serve.

Run by the container on every boot. Each step is safe to repeat, so a redeploy
migrates forward and refreshes the workbooks without duplicating anything.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

from sqlalchemy import text

from app.config import get_settings
from app.database import engine

WAIT_SECONDS = int(os.getenv("DB_WAIT_SECONDS", "60"))


def wait_for_database() -> None:
    """A managed database can still be starting when the app container is."""
    settings = get_settings()
    if not settings.is_postgres:
        return
    deadline = time.monotonic() + WAIT_SECONDS
    attempt = 0
    while True:
        attempt += 1
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            print(f"Database reachable after {attempt} attempt(s).", flush=True)
            return
        except Exception as exc:  # noqa: BLE001 - any driver error is a retry
            if time.monotonic() >= deadline:
                print(f"Database not reachable after {WAIT_SECONDS}s: {exc}", file=sys.stderr, flush=True)
                raise
            print(f"Waiting for the database ({attempt})...", flush=True)
            time.sleep(2)


def run(step: str, *command: str) -> None:
    print(f"\n=== {step} ===", flush=True)
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        print(f"{step} failed with exit code {result.returncode}", file=sys.stderr, flush=True)
        raise SystemExit(result.returncode)


def main() -> None:
    settings = get_settings()
    print(f"Database: {'postgresql' if settings.is_postgres else 'sqlite'}", flush=True)
    wait_for_database()

    run("Applying database migrations", sys.executable, "-m", "alembic", "upgrade", "head")
    run("Seeding the demonstration data", sys.executable, "bootstrap.py")

    port = os.getenv("PORT", "8000")
    print(f"\n=== Serving on port {port} ===", flush=True)
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "gateway:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
            "--proxy-headers",
            "--forwarded-allow-ips",
            "*",
        ],
    )


if __name__ == "__main__":
    main()

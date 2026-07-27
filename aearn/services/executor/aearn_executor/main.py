"""CLI entry point for the standalone executor process; no HTTP surface exists."""
from __future__ import annotations

import argparse
import time

import psycopg
from aearn_shared.execution import load_runtime_catalog_registry
from docker.errors import DockerException
from psycopg.rows import dict_row

from aearn_executor.docker_client import DockerContainerRuntimeClient
from aearn_executor.repository import PostgresExecutionJobStore
from aearn_executor.service import ExecutorService
from aearn_executor.settings import ExecutorSettings
from aearn_executor.trusted_input import PostgresTrustedInputResolver


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the isolated Aearn executor process.")
    parser.add_argument("--once", action="store_true", help="Refresh health and process at most one durable job.")
    args = parser.parse_args(argv)
    settings = ExecutorSettings.from_environment()
    registry = load_runtime_catalog_registry(
        catalog_path=settings.registry_root / "runtime-catalog.json",
        image_locks_path=settings.registry_root / "image-locks.json",
    )
    try:
        with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
            store = PostgresExecutionJobStore(conn)
            service = ExecutorService(
                store=store,
                input_resolver=PostgresTrustedInputResolver(conn),
                runtime_client=DockerContainerRuntimeClient(),
                registry=registry,
                settings=settings,
            )
            while True:
                service.run_once()
                conn.commit()
                if args.once:
                    return 0
                time.sleep(settings.poll_interval_seconds)
    except KeyboardInterrupt:
        return 0
    except (DockerException, OSError, RuntimeError, ValueError, psycopg.Error):
        # Deliberately avoid raw engine/database diagnostics in normal output.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

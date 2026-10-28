"""CPU-only startup boundaries: never use the DB, broker, provider or sidecar."""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any

import psycopg
import pytest
from celery import Celery  # type: ignore[import-untyped]
from celery.apps.beat import Beat  # type: ignore[import-untyped]
from celery.beat import PersistentScheduler, Service  # type: ignore[import-untyped]
from celery.worker.worker import WorkController  # type: ignore[import-untyped]
from starlette.types import Message

from aearn_worker import worker_app
from app.db import completion_baseline


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch: pytest.MonkeyPatch) -> Iterator[asyncio.AbstractEventLoop]:
    # Windows creates a local socketpair for the event loop's wakeup pipe.
    # Construct only that CPU-test plumbing before blocking network connects.
    loop = asyncio.new_event_loop()
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("startup CPU test attempted external IO")

    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(psycopg.Connection, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setenv("LLM_TYPE", "disabled")
    try:
        yield loop
    finally:
        loop.close()


def offline_app() -> Any:
    # Exercise the guarded components without mutating the imported application.
    # Fresh-interpreter tests below separately verify production env selection.
    app = Celery(
        "startup-cpu",
        loader=worker_app.ContractLoader,
        broker="memory://",
        backend="cache+memory://",
        fixups=[],
        set_as_current=False,
    )
    app.conf.beat_scheduler = worker_app.ContractScheduler
    return app


def test_imports_do_not_run_check_or_database_io() -> None:
    # A fresh interpreter, not a cached import; no service is started.
    program = """
import socket
import psycopg

def forbidden(*args, **kwargs):
    raise AssertionError('import attempted startup check or external IO')

socket.socket.connect = forbidden
psycopg.connect = forbidden
psycopg.Connection.connect = forbidden
from app.db import completion_baseline
completion_baseline.ensure_startup_contract = forbidden
import app.main
import aearn_worker.worker_app
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env={**os.environ, "LLM_TYPE": "disabled", "AEARN_DATABASE_CONTRACT": "completion_non_b1d_v1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("contract", [None, "completion_non_b1d_v1", ""])
def test_production_celery_configuration_is_opt_in(contract: str | None) -> None:
    program = """
import json
import os
import socket
import sys
import types
import psycopg
from celery.loaders.app import AppLoader

def forbidden(*args, **kwargs):
    raise AssertionError('configuration attempted external IO')
psycopg.connect = forbidden
psycopg.Connection.connect = forbidden
socket.socket.connect = forbidden
fixture = types.ModuleType('startup_legacy_fixture')
class LegacyLoader(AppLoader):
    pass
fixture.LegacyLoader = LegacyLoader
fixture.beat_scheduler = 'celery.beat:Scheduler'
sys.modules[fixture.__name__] = fixture
os.environ['CELERY_LOADER'] = 'startup_legacy_fixture:LegacyLoader'
os.environ['CELERY_CONFIG_MODULE'] = fixture.__name__
os.environ['CELERY_BROKER_URL'] = 'memory://'
os.environ['CELERY_RESULT_BACKEND'] = 'cache+memory://'
contract = json.loads(sys.argv[1])
if contract is None:
    os.environ.pop('AEARN_DATABASE_CONTRACT', None)
else:
    os.environ['AEARN_DATABASE_CONTRACT'] = contract
from aearn_worker import worker_app
from app.db import completion_baseline
app = worker_app.celery_app
if contract is None:
    assert isinstance(app.loader, LegacyLoader)
    assert app.conf.beat_scheduler == 'celery.beat:Scheduler'
else:
    assert isinstance(app.loader, worker_app.ContractLoader)
    assert app.conf.beat_scheduler is worker_app.ContractScheduler
    if contract == '':
        try:
            app.loader.init_worker()
        except completion_baseline.CompletionBaselineError as exc:
            assert str(exc) == 'COMPLETION_BASELINE_CONTRACT_REJECTED'
        else:
            raise AssertionError('explicit empty contract was accepted')
        assert not app.loader.worker_initialized
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", program, json.dumps(contract)],
        env={**os.environ, "LLM_TYPE": "disabled"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("entrypoint", "database", "user", "contract", "error"),
    [
        ("worker-main", "postgres", "postgres", None, None),
        ("worker-codex", "postgres", "postgres", None, None),
        ("beat", "postgres", "postgres", None, None),
        ("worker-main", completion_baseline.VALIDATION_DATABASE_NAME, "postgres", None,
         "COMPLETION_BASELINE_CONTRACT_REQUIRED"),
        ("beat", completion_baseline.VALIDATION_DATABASE_NAME, "postgres", None,
         "COMPLETION_BASELINE_CONTRACT_REQUIRED"),
        ("worker-codex", "postgres", "aearn_cb_runtime_20261027", None,
         "COMPLETION_BASELINE_CONTRACT_REQUIRED"),
        ("beat", "postgres", "aearn_cb_verifier_20261027", None,
         "COMPLETION_BASELINE_CONTRACT_REQUIRED"),
        ("beat", "postgres", "aearn_cb_runtime_20261027", "completion_non_b1d_v1",
         "COMPLETION_BASELINE_CATALOG_NOT_CANONICAL"),
    ],
)
def test_production_worker_and_custom_beat_gate_actual_settings_scope(
    entrypoint: str, database: str, user: str, contract: str | None, error: str | None,
) -> None:
    # Import the real production app in a fresh process. Only stop at the worker
    # bootstep / scheduler-start boundary; no live worker or beat service runs.
    program = """
import json
import os
import socket
import sys
import types
import psycopg
from celery.apps.beat import Beat
from celery.beat import Scheduler
from celery.loaders.app import AppLoader
from celery.worker.worker import WorkController

entrypoint, database, user, contract, error = json.loads(sys.argv[1])
events = []
def forbidden(*args, **kwargs):
    raise AssertionError('production assembly attempted external IO')
psycopg.connect = forbidden
psycopg.Connection.connect = forbidden
socket.socket.connect = forbidden
fixture = types.ModuleType('startup_assembly_fixture')
class LegacyLoader(AppLoader):
    def init_worker(self):
        events.append('legacy-init')
        super().init_worker()
class CustomScheduler(Scheduler):
    def setup_schedule(self):
        events.append('custom-scheduler-setup')
fixture.LegacyLoader = LegacyLoader
fixture.beat_scheduler = CustomScheduler
sys.modules[fixture.__name__] = fixture
os.environ['CELERY_LOADER'] = 'startup_assembly_fixture:LegacyLoader'
os.environ['CELERY_CONFIG_MODULE'] = fixture.__name__
os.environ['CELERY_BROKER_URL'] = 'memory://'
os.environ['CELERY_RESULT_BACKEND'] = 'cache+memory://'
# Actual cached Settings may differ from os.environ (including dotenv sources).
# Do not inspect real .env files or secrets to exercise that precedence.
os.environ['DATABASE_URL'] = 'postgresql://offline:offline@127.0.0.1:1/offline'
if contract is None:
    os.environ.pop('AEARN_DATABASE_CONTRACT', None)
else:
    os.environ['AEARN_DATABASE_CONTRACT'] = contract
from app.core import config
from app.db import completion_baseline

def get_settings():
    events.append('settings')
    return types.SimpleNamespace(
        database_url=f'postgresql://{user}:offline@127.0.0.1:1/{database}')
config.get_settings = get_settings
real_check = completion_baseline.ensure_startup_contract
def check(*, entrypoint):
    events.append('check:' + entrypoint)
    real_check(entrypoint=entrypoint)
def reject_catalog():
    events.append('catalog')
    raise completion_baseline.CompletionBaselineError(
        'COMPLETION_BASELINE_CATALOG_NOT_CANONICAL')
completion_baseline.ensure_startup_contract = check
completion_baseline.check_completion_baseline = reject_catalog
from aearn_worker import worker_app
app = worker_app.celery_app
assert events == [], 'cold import called Settings or the startup checker'
if contract is None:
    assert type(app.loader) is LegacyLoader
    assert app.conf.beat_scheduler is CustomScheduler
else:
    assert isinstance(app.loader, worker_app.ContractLoader)
# Configuring/accessing the loader must also remain cold.
assert events == []
app.loader.import_default_modules = lambda: events.append('task-imports')
WorkController.setup_instance = lambda *args, **kwargs: events.append('bootsteps')
app.finalize = lambda *args, **kwargs: events.append('finalize')
Beat.set_process_title = lambda self: events.append('process-title')
# End before constructing any service, store, publisher, or runtime.
Beat.start_scheduler = lambda self: events.append('scheduler-start-boundary')

def start():
    if entrypoint == 'beat':
        # Real -S/custom scheduler selection, not the guarded default scheduler.
        beat = Beat(app=app, scheduler=CustomScheduler, quiet=True)
        assert beat.scheduler_cls is CustomScheduler
        beat.run()
    else:
        queue = 'tutor-codex' if entrypoint == 'worker-codex' else 'celery,tutor-interactive'
        WorkController(app=app, queues=queue, pool='solo')

if error is not None:
    for attempt in range(2):
        events.clear()
        try:
            start()
        except completion_baseline.CompletionBaselineError as exc:
            assert str(exc) == error
        else:
            raise AssertionError('protected DSN reached consumer/scheduler boundary')
        expected = ['check:worker', 'settings']
        if contract is not None:
            expected.append('catalog')
        assert events == expected, events
        assert not app.loader.worker_initialized
else:
    start()
    expected = ['check:worker', 'settings', 'legacy-init', 'task-imports']
    expected += (['finalize', 'process-title', 'scheduler-start-boundary']
                 if entrypoint == 'beat' else ['bootsteps'])
    assert events == expected, events
    assert app.loader.worker_initialized
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", program,
         json.dumps([entrypoint, database, user, contract, error])],
        env={**os.environ, "LLM_TYPE": "disabled"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("reject", [False, True])
def test_real_asgi_lifespan_fails_before_startup_complete(
    monkeypatch: pytest.MonkeyPatch, reject: bool,
    no_external_io: asyncio.AbstractEventLoop,
) -> None:
    from app import main

    events: list[str] = []

    def check(*, entrypoint: str) -> None:
        events.append(entrypoint)
        if reject:
            raise RuntimeError("contract rejected")

    monkeypatch.setattr(main, "ensure_startup_contract", check)

    async def drive() -> None:
        messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

        async def receive() -> dict[str, str]:
            return next(messages)

        async def send(message: Message) -> None:
            events.append(str(message["type"]))

        await main.app({"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send)

    if reject:
        with pytest.raises(RuntimeError, match="contract rejected"):
            no_external_io.run_until_complete(drive())
        assert events == ["api", "lifespan.startup.failed"]
    else:
        no_external_io.run_until_complete(drive())
        assert events == ["api", "lifespan.startup.complete", "lifespan.shutdown.complete"]


@pytest.mark.parametrize("queue", ["celery,tutor-interactive", "tutor-codex"])
@pytest.mark.parametrize("reject", [False, True])
def test_workcontroller_loader_gate_precedes_all_worker_bootsteps(
    monkeypatch: pytest.MonkeyPatch, queue: str, reject: bool,
) -> None:
    app = offline_app()
    events: list[str] = []

    def check(*, entrypoint: str) -> None:
        events.append(entrypoint)
        if reject:
            raise RuntimeError("contract rejected")

    monkeypatch.setattr(completion_baseline, "ensure_startup_contract", check)
    monkeypatch.setattr(app.loader, "import_default_modules", lambda: events.append("task-imports"))
    # This is the real controller's boundary at which Pool/Beat/Consumer
    # bootsteps would be constructed. Never construct or start live services.
    monkeypatch.setattr(WorkController, "setup_instance", lambda *a, **kw: events.append("bootsteps"))
    if reject:
        for _ in range(2):
            with pytest.raises(RuntimeError, match="contract rejected"):
                WorkController(app=app, queues=queue, pool="solo")
            assert not app.loader.worker_initialized
        assert events == ["worker", "worker"]
    else:
        WorkController(app=app, queues=queue, pool="solo")
        assert events == ["worker", "task-imports", "bootsteps"]
        app.loader.init_worker()
        assert events == ["worker", "task-imports", "bootsteps"]


def test_beat_run_loader_rejects_before_finalize_or_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    app = offline_app()
    events: list[str] = []

    def check(*, entrypoint: str) -> None:
        events.append(entrypoint)
        raise RuntimeError("contract rejected")

    monkeypatch.setattr(completion_baseline, "ensure_startup_contract", check)
    monkeypatch.setattr(app, "finalize", lambda *a, **kw: events.append("finalize"))
    monkeypatch.setattr(Beat, "set_process_title", lambda self: events.append("process-title"))
    monkeypatch.setattr(Beat, "start_scheduler", lambda self: events.append("scheduler"))
    with pytest.raises(RuntimeError, match="contract rejected"):
        Beat(app=app, quiet=True).run()
    assert events == ["worker"]


@pytest.mark.parametrize("reject", [False, True])
def test_beat_service_materializes_guarded_scheduler_before_first_tick(
    monkeypatch: pytest.MonkeyPatch, reject: bool,
) -> None:
    app = offline_app()
    events: list[str] = []
    beat = Beat(app=app)
    service = Service(app=app, scheduler_cls=beat.scheduler_cls)

    def check(*, entrypoint: str) -> None:
        events.append(entrypoint)
        if reject:
            raise RuntimeError("contract rejected")

    def tick(self: Any) -> None:
        events.append("first-tick-publish-boundary")
        service._is_shutdown.set()

    monkeypatch.setattr(completion_baseline, "ensure_startup_contract", check)
    monkeypatch.setattr(PersistentScheduler, "setup_schedule", lambda self: events.append("schedule-store"))
    monkeypatch.setattr(PersistentScheduler, "close", lambda self: None)
    monkeypatch.setattr(worker_app.ContractScheduler, "tick", tick)
    # Celery banner constructs a lazy scheduler. It must not open the DB/store;
    # the materialized scheduler must still check before reaching its tick.
    assert isinstance(service.get_scheduler(lazy=True), worker_app.ContractScheduler)
    assert events == []
    if reject:
        with pytest.raises(RuntimeError, match="contract rejected"):
            service.start()
        assert events == ["beat"]
    else:
        service.start()
        assert events == ["beat", "schedule-store", "first-tick-publish-boundary"]


def test_unset_contract_keeps_real_loader_and_scheduler_legacy_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AEARN_DATABASE_CONTRACT", raising=False)
    app = offline_app()
    events: list[str] = []
    monkeypatch.setattr(app.loader, "import_default_modules", lambda: events.append("task-imports"))
    monkeypatch.setattr(PersistentScheduler, "setup_schedule", lambda self: events.append("schedule-store"))
    app.loader.init_worker()
    worker_app.ContractScheduler(app=app)
    assert events == ["task-imports", "schedule-store"]


def test_dev_script_requires_readonly_gate_and_controlled_restart() -> None:
    root = Path(__file__).resolve().parents[4]
    script = (root / "scripts/start-dev.ps1").read_text(encoding="utf-8")
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    for name in ("dev", "dev:restart", "dev:stop", "dev:status", "dev:no-codex"):
        assert package["scripts"][name].startswith("pwsh -NoProfile ")
    assert '-FilePath "pwsh"' in script
    assert "-WindowStyle Hidden" in script
    assert 'PSEdition -ne "Core"' in script
    assert '"--contract", "completion_non_b1d_v1", "--check"' in script
    gate = script.index('Write-Step "checking completion_non_b1d_v1')
    selection_rejection = script.index('if (-not $completionContractSelected) {')
    docker_start = script.index('Write-Step "starting PostgreSQL and Redis"')
    start = script.index('$state.apiPid = Start-ManagedProcess')
    assert selection_rejection < docker_start < gate < start
    assert 'bootstrapping database schema' not in script
    assert '} elseif (-not $SkipBootstrap)' not in script
    assert 'cannot run legacy DDL or seeds' in script
    assert script.index('$completionContractSelected =') < script.index('} elseif ($Restart)')
    assert 'if (-not $completionContractSelected -and (Test-Http $apiHealthUrl))' in script
    assert 'Assert-CompletionStartupQuiescent' in script
    assert 'automatic -Restart is disabled' in script
    assert 'Application startup complete' in script
    assert 'aearn beat scheduler startup complete$' in script
    assert 'Managed startup requires AEARN_DATABASE_CONTRACT=completion_non_b1d_v1' in script
    assert 'json.dumps(os.environ.get' in script
    assert 'tutor-main@' in script and r'ready\.$' in script
    assert 'not database-contract readiness' in script

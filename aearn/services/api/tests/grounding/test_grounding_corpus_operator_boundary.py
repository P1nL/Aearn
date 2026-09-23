"""Offline, source-level audit of the phase-I corpus operator boundary."""

from __future__ import annotations

import ast
import re
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[2]
AEARN_DIR = API_DIR.parents[1]
APP_DIR = API_DIR / "app"
WORKER_DIR = AEARN_DIR / "services" / "worker" / "aearn_worker"
START_DEV = AEARN_DIR / "scripts" / "start-dev.ps1"
GROUNDING_DIR = APP_DIR / "services" / "grounding"

# The CLI may use its service and the service may use fixtures. No other
# API/worker module may depend on these operator-only modules.
OPERATOR_MODULES = frozenset({"corpus_cli", "corpus_service", "corpus_fixtures"})
OPERATOR_REFERENCE = re.compile(r"\b(?:corpus_cli|corpus_service|corpus_fixtures)\b")
AUTOMATIC_CORPUS_TASK = re.compile(r"(?:corpus|reindex)", re.IGNORECASE)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _operator_references(path: Path) -> list[str]:
    """Find imports, attributes and dynamic-import string references."""
    references: list[str] = []
    for node in ast.walk(_parse(path)):
        values: list[str] = []
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            values.extend((node.module or "", *(alias.name for alias in node.names)))
        elif isinstance(node, ast.Attribute):
            values.append(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append(node.value)
        for value in values:
            if OPERATOR_REFERENCE.search(value):
                references.append(f"{path}:{node.lineno}: {value}")
    return references


def _attribute_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attribute_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _config_literal(path: Path, name: str) -> dict[str, object]:
    assignments = [
        node.value
        for node in _parse(path).body
        if isinstance(node, ast.Assign)
        and any(_attribute_name(target) == name for target in node.targets)
    ]
    assert len(assignments) == 1, f"{path}: expected one literal {name} assignment"
    value = ast.literal_eval(assignments[0])
    assert isinstance(value, dict), f"{path}: {name} must be a literal mapping"
    return value


def test_api_router_inventory_is_explicit_without_operator_registration() -> None:
    main = APP_DIR / "main.py"
    tree = _parse(main)
    router_imports = {
        alias.asname or alias.name: node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("app.routes.")
        for alias in node.names
        if alias.name == "router"
    }
    includes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _attribute_name(node.func) == "app.include_router"
    ]
    assert router_imports, f"{main}: no statically imported route inventory"
    included_names = [
        node.args[0].id
        if len(node.args) == 1 and isinstance(node.args[0], ast.Name) and not node.keywords
        else None
        for node in includes
    ]
    assert None not in included_names, f"{main}: dynamic include_router bypasses static audit"
    assert len(included_names) == len(set(included_names)), f"{main}: duplicate router include"
    assert set(included_names) == set(router_imports), (
        f"{main}: included routers differ from app.routes imports: "
        f"included={included_names}, imports={router_imports}"
    )


def test_runtime_api_and_learner_modules_do_not_reference_operator_modules() -> None:
    # Covers routes, startup, learning capabilities, Lesson/Tutor consumers and
    # package exports, not just main.py; operator-internal dependencies are allowed.
    allowed = {GROUNDING_DIR / f"{name}.py" for name in OPERATOR_MODULES}
    assert all(path.is_file() for path in allowed), (
        f"{GROUNDING_DIR}: expected CLI/service/fixture modules for the boundary audit"
    )
    scanned = [path for path in APP_DIR.rglob("*.py") if path not in allowed]
    assert scanned, f"{APP_DIR}: no runtime Python modules audited"
    references = [ref for path in scanned for ref in _operator_references(path)]
    assert not references, "Operator module reference outside operator package:\n" + "\n".join(
        references
    )


def test_worker_tasks_routes_and_beat_have_no_operator_path() -> None:
    worker_app = WORKER_DIR / "worker_app.py"
    schedule = _config_literal(worker_app, "celery_app.conf.beat_schedule")
    routes = _config_literal(worker_app, "celery_app.conf.task_routes")
    assert schedule, f"{worker_app}: no beat entries audited"
    assert routes, f"{worker_app}: no task routes audited"
    tasks = [
        (entry, definition.get("task"))
        for entry, definition in schedule.items()
        if isinstance(definition, dict)
    ]
    assert len(tasks) == len(schedule), f"{worker_app}: nonliteral beat entry"
    for entry, task in tasks:
        assert isinstance(task, str) and not AUTOMATIC_CORPUS_TASK.search(f"{entry} {task}"), (
            f"{worker_app}: beat entry {entry!r} schedules corpus/reindex task {task!r}"
        )
    for task in routes:
        assert isinstance(task, str) and not AUTOMATIC_CORPUS_TASK.search(task), (
            f"{worker_app}: task route {task!r} exposes corpus/reindex operation"
        )
    scanned = list(WORKER_DIR.rglob("*.py"))
    assert scanned, f"{WORKER_DIR}: no worker Python modules audited"
    references = [ref for path in scanned for ref in _operator_references(path)]
    assert not references, "Worker operator module reference:\n" + "\n".join(references)


def test_normal_dev_startup_only_launches_api_and_worker_entrypoints() -> None:
    source = START_DEV.read_text(encoding="utf-8")
    assert "python -m uvicorn app.main:app" in source, f"{START_DEV}: API entrypoint changed"
    assert "aearn_worker.worker_app:celery_app worker" in source, (
        f"{START_DEV}: worker entrypoint changed"
    )
    assert "aearn_worker.worker_app:celery_app beat" in source, (
        f"{START_DEV}: beat entrypoint changed"
    )
    forbidden = re.compile(
        r"\b(?:corpus_cli|corpus_service|corpus_fixtures|"
        r"grounding_reindex|run_fixture_grounding_reindex)\b"
    )
    references = [
        f"{START_DEV}:{line_number}: {line.strip()}"
        for line_number, line in enumerate(source.splitlines(), start=1)
        if forbidden.search(line)
    ]
    assert not references, "Startup references corpus operator/fixture:\n" + "\n".join(
        references
    )

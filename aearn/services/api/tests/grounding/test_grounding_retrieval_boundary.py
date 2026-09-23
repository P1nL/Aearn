"""Offline source-wiring audit of the phase-I retrieval v2 boundary.

This is not a database, call-graph, or live provider verification.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2]
AEARN_DIR = API_DIR.parents[1]
APP_DIR = API_DIR / "app"
GROUNDING_DIR = APP_DIR / "services" / "grounding"
SHADOW_ADAPTER = APP_DIR / "services" / "learning" / "grounding_adapters.py"
WORKER_DIR = AEARN_DIR / "services" / "worker" / "aearn_worker"
START_DEV = AEARN_DIR / "scripts" / "start-dev.ps1"
IMPLEMENTATION = frozenset({"hybrid_retrieval", "retrieval_planner"})
V2_MODULES = IMPLEMENTATION | {"retrieval_contracts", "coverage"}
PACKAGE = "app.services.grounding"
LOADERS = frozenset({"importlib.import_module", "import_module", "__import__"})
EXTERNAL_ROOTS = frozenset({
    "pgvector", "sentence_transformers", "fastembed", "chromadb", "qdrant_client",
    "pinecone", "weaviate", "openai", "anthropic", "cohere", "voyageai",
    "httpx", "requests", "aiohttp", "urllib", "http", "socket",
})
EMBEDDING_PACKAGES = frozenset({
    "pgvector", "sentence-transformers", "fastembed", "chromadb", "qdrant-client",
    "pinecone-client", "weaviate-client", "openai", "anthropic", "cohere",
    "voyageai", "langchain-openai",
})


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _implementation_references(tree: ast.Module) -> list[tuple[int, str]]:
    """Ignore DTOs, prose, common coverage fields and uncalled string literals."""
    references: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(f"{PACKAGE}.") and (
                    alias.name.split(".")[3] in IMPLEMENTATION
                ):
                    references.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module in {f"{PACKAGE}.{name}" for name in IMPLEMENTATION}:
                references.append((node.lineno, str(node.module)))
            elif node.module == PACKAGE or (node.level and node.module in {None, "grounding"}):
                references.extend(
                    (node.lineno, alias.name)
                    for alias in node.names if alias.name in IMPLEMENTATION
                )
        elif isinstance(node, ast.Call):
            callee = _dotted(node.func)
            if callee in LOADERS and node.args:
                path = node.args[0]
                if isinstance(path, ast.Constant) and path.value in {
                    f"{PACKAGE}.{name}" for name in IMPLEMENTATION
                }:
                    references.append((node.lineno, str(path.value)))
            if callee == "getattr" and len(node.args) >= 2:
                name = node.args[1]
                if isinstance(name, ast.Constant) and name.value in IMPLEMENTATION:
                    references.append((node.lineno, str(name.value)))
        elif isinstance(node, ast.Attribute) and node.attr in IMPLEMENTATION:
            references.append((node.lineno, node.attr))
    return references


def _external_imports(tree: ast.Module) -> list[tuple[int, str]]:
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        elif isinstance(node, ast.Call) and _dotted(node.func) in LOADERS and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                names = [first.value]
        imports.extend(
            (node.lineno, name) for name in names if name.split(".")[0] in EXTERNAL_ROOTS
        )
    return imports


def test_audit_detects_wiring_but_not_data_only_mentions() -> None:
    wired = ast.parse(
        "from app.services.grounding.hybrid_retrieval import retrieve\n"
        "from app.services.grounding import retrieval_planner\n"
        "importlib.import_module('app.services.grounding.hybrid_retrieval')\n"
        "getattr(grounding, 'retrieval_planner')\n"
    )
    assert len(_implementation_references(wired)) == 4
    data_only = ast.parse(
        '"""hybrid_retrieval is mentioned in prose."""\n'
        "coverage = {'retrieval_planner': 'label', 'coverage': 'partial'}\n"
        "class CoverageReport: pass\n"
        "from app.services.grounding.retrieval_contracts import CoverageReport\n"
    )
    assert not _implementation_references(data_only)


def test_public_api_worker_and_startup_do_not_reference_v2_implementation() -> None:
    owned = {GROUNDING_DIR / f"{name}.py" for name in V2_MODULES}
    # Child06 permits exactly this explicit internal shadow adapter to resolve
    # the server-owned v2 plan. Its separate audit forbids app/worker consumers
    # of the adapter; all other runtime files remain excluded here.
    owned.add(SHADOW_ADAPTER)
    assert all(path.is_file() for path in owned), "v2 modules or shadow adapter missing"
    assert any(value == f"{PACKAGE}.retrieval_planner"
               for _, value in _implementation_references(_parse(SHADOW_ADAPTER)))
    runtime = [path for path in APP_DIR.rglob("*.py") if path not in owned]
    worker = list(WORKER_DIR.rglob("*.py"))
    assert runtime and worker, "API/worker source inventory missing"
    references = [
        f"{path}:{line}: {value}"
        for path in (*runtime, *worker)
        for line, value in _implementation_references(_parse(path))
    ]
    assert not references, "v2 runtime/worker reference:\n" + "\n".join(references)
    startup = [
        f"{START_DEV}:{line}: {text.strip()}"
        for line, text in enumerate(START_DEV.read_text(encoding="utf-8").splitlines(), 1)
        if not text.lstrip().startswith("#")
        and re.search(r"\b(?:hybrid_retrieval|retrieval_planner)\b", text)
    ]
    assert not startup, "v2 invoked by dev startup:\n" + "\n".join(startup)


def test_worker_schedule_and_routes_have_no_v2_task_reference() -> None:
    worker_app = WORKER_DIR / "worker_app.py"
    assignments = {
        _dotted(target): node.value
        for node in _parse(worker_app).body
        if isinstance(node, ast.Assign)
        for target in node.targets
    }
    keys = ("celery_app.conf.beat_schedule", "celery_app.conf.task_routes")
    assert all(key in assignments for key in keys), "worker schedule/route inventory changed"
    for key in keys:
        config = ast.literal_eval(assignments[key])
        assert isinstance(config, dict)
        task_names = (
            [entry.get("task") for entry in config.values() if isinstance(entry, dict)]
            if key.endswith("beat_schedule") else list(config)
        )
        assert len(task_names) == len(config), "nonliteral worker task mapping"
        assert all(isinstance(name, str) for name in task_names)
        assert not [
            name for name in task_names
            if any(module in name for module in IMPLEMENTATION)
        ], f"{worker_app}: v2 scheduled or routed through {key}"


def test_v2_modules_do_not_import_provider_http_vector_or_expose_auto_entrypoints() -> None:
    paths = [GROUNDING_DIR / f"{name}.py" for name in sorted(V2_MODULES)]
    assert all(path.is_file() for path in paths), "v2 modules not yet complete"
    violations: list[str] = []
    for path in paths:
        tree = _parse(path)
        violations.extend(f"{path}:{line}: import {name}" for line, name in _external_imports(tree))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    target = decorator.func if isinstance(decorator, ast.Call) else decorator
                    name = _dotted(target)
                    if name and name.rsplit(".", 1)[-1] in {
                        "task", "get", "post", "put", "delete", "patch", "on_event",
                    }:
                        violations.append(f"{path}:{node.lineno}: decorator {name}")
            elif isinstance(node, ast.Call):
                name = _dotted(node.func)
                if name and name.rsplit(".", 1)[-1] in {"include_router", "add_periodic_task"}:
                    violations.append(f"{path}:{node.lineno}: entrypoint {name}")
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any((_dotted(target) or "").endswith(".beat_schedule") for target in targets):
                    violations.append(f"{path}:{node.lineno}: beat schedule")
    assert not violations, "v2 external dependency/entrypoint:\n" + "\n".join(violations)


def test_api_runtime_dependencies_do_not_require_embedding_provider() -> None:
    config = tomllib.loads((API_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = config["project"]["dependencies"]
    assert isinstance(dependencies, list)
    names = {
        re.split(r"[\s[<>=!~;]", dependency, maxsplit=1)[0].lower().replace("_", "-")
        for dependency in dependencies
    }
    assert not names & EMBEDDING_PACKAGES, (
        f"mandatory embedding/vector dependency: {names & EMBEDDING_PACKAGES}"
    )

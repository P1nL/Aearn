"""Offline source audit for the phase-I, unconnected plan proposal sidecar.

This checks wiring and obvious side effects, not a transitive call graph or DB
read-only permissions. Functional proposal semantics live in separate tests.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[2]
AEARN_DIR = API_DIR.parents[1]
APP_DIR = API_DIR / "app"
LEARNING_DIR = APP_DIR / "services" / "learning"
WORKER_DIR = AEARN_DIR / "services" / "worker" / "aearn_worker"
START_DEV = AEARN_DIR / "scripts" / "start-dev.ps1"
PACKAGE = "app.services.learning"
REQUIRED = frozenset({"plan_coverage", "plan_migration"})

# These existed before this child. Do not treat the public plan service as a
# new sidecar module just because its name starts with plan_.
EXISTING_PLAN_MODULES = frozenset({
    "plan_capability", "plan_drafting", "plan_policy", "plan_repository",
    "plan_service", "plan_tools",
})
LOADERS = frozenset({"importlib.import_module", "import_module", "__import__"})
OPERATOR_MODULES = frozenset({
    "corpus_cli", "corpus_service", "corpus_fixtures", "corpus_fixture_policy",
})
NETWORK_ROOTS = frozenset({
    "httpx", "requests", "aiohttp", "urllib", "http", "socket",
    "openai", "anthropic", "cohere", "voyageai",
})
MUTATING_SQL = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE\s+[\w.]+\s+SET|DELETE\s+FROM|"
    r"TRUNCATE\s+(?:TABLE\s+)?|CREATE\s+(?:TABLE|INDEX)|"
    r"ALTER\s+TABLE|DROP\s+(?:TABLE|INDEX))\b",
    re.IGNORECASE,
)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _imports(tree: ast.Module) -> list[tuple[int, str]]:
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.append((node.lineno, module))
            imports.extend((node.lineno, f"{module}.{alias.name}") for alias in node.names)
        elif isinstance(node, ast.Call) and _dotted(node.func) in LOADERS and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                imports.append((node.lineno, first.value))
    return imports


def _sidecar_modules() -> frozenset[str]:
    """Own required modules plus their new plan-prefixed sibling dependencies."""
    assert all((LEARNING_DIR / f"{name}.py").is_file() for name in REQUIRED), (
        "plan preflight/migration modules not yet complete"
    )
    owned = set(REQUIRED)
    pending = list(REQUIRED)
    while pending:
        tree = _parse(LEARNING_DIR / f"{pending.pop()}.py")
        for _, imported in _imports(tree):
            # Relative imports lose leading dots here; absolute imports are
            # scoped to this package, not arbitrary lookalikes.
            if imported.startswith(f"{PACKAGE}."):
                name = imported.removeprefix(f"{PACKAGE}.").split(".", 1)[0]
            elif imported.startswith("plan_"):
                name = imported.split(".", 1)[0]
            else:
                continue
            path = LEARNING_DIR / f"{name}.py"
            if name.startswith("plan_") and name not in EXISTING_PLAN_MODULES and path.is_file():
                if name not in owned:
                    owned.add(name)
                    pending.append(name)
    return frozenset(owned)


def _sidecar_references(tree: ast.Module, owned: frozenset[str]) -> list[tuple[int, str]]:
    references: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            references.extend(
                (node.lineno, alias.name)
                for alias in node.names
                if alias.name in {f"{PACKAGE}.{name}" for name in owned}
            )
        elif isinstance(node, ast.ImportFrom):
            if node.module in {f"{PACKAGE}.{name}" for name in owned} or (
                node.level and node.module in owned | {f"learning.{name}" for name in owned}
            ):
                references.append((node.lineno, str(node.module)))
            elif node.module == PACKAGE or (node.level and node.module in {None, "learning"}):
                references.extend(
                    (node.lineno, alias.name) for alias in node.names if alias.name in owned
                )
        elif isinstance(node, ast.Call):
            callee = _dotted(node.func)
            if callee in LOADERS and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and first.value in {
                    f"{PACKAGE}.{name}" for name in owned
                }:
                    references.append((node.lineno, str(first.value)))
            if callee == "getattr" and len(node.args) >= 2:
                name = node.args[1]
                if isinstance(name, ast.Constant) and name.value in owned:
                    references.append((node.lineno, str(name.value)))
        elif isinstance(node, ast.Attribute) and node.attr in owned:
            references.append((node.lineno, node.attr))
    return references


def _sidecar_violations(tree: ast.Module) -> list[tuple[int, str]]:
    violations: list[tuple[int, str]] = []
    for line, imported in _imports(tree):
        parts = set(imported.split("."))
        if parts & OPERATOR_MODULES:
            violations.append((line, f"operator/fixture import {imported}"))
        if imported.split(".")[0] in NETWORK_ROOTS or imported.startswith(
            ("app.services.llm.", "app.services.grounding.grounding_fetch")
        ):
            violations.append((line, f"provider/network import {imported}"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if MUTATING_SQL.search(node.value):
                violations.append((node.lineno, "mutation SQL"))
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name and name.rsplit(".", 1)[-1] in {"commit", "executemany"}:
                violations.append((node.lineno, f"write-capable call {name}"))
            if name and name.rsplit(".", 1)[-1] in {"include_router", "add_periodic_task"}:
                violations.append((node.lineno, f"automatic entrypoint {name}"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                name = _dotted(target)
                if name and name.rsplit(".", 1)[-1] in {
                    "task", "get", "post", "put", "patch", "delete", "on_event",
                }:
                    violations.append((node.lineno, f"automatic decorator {name}"))
        elif isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            check = node.test
            if (isinstance(check.left, ast.Name) and check.left.id == "__name__"
                    and len(check.comparators) == 1
                    and isinstance(check.comparators[0], ast.Constant)
                    and check.comparators[0].value == "__main__"):
                violations.append((node.lineno, "module CLI entrypoint"))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any((_dotted(target) or "").endswith(".beat_schedule") for target in targets):
                violations.append((node.lineno, "beat schedule assignment"))
    return violations


def test_audit_detects_wiring_but_ignores_inert_data() -> None:
    wired = ast.parse(
        "from app.services.learning.plan_coverage import PlanCoveragePreflightService\n"
        "from app.services.learning import plan_migration\n"
        "importlib.import_module('app.services.learning.plan_coverage')\n"
        "getattr(learning, 'plan_migration')\n"
        "from .plan_coverage import NodeSourceRequirement\n"
    )
    assert len(_sidecar_references(wired, REQUIRED)) == 5
    inert = ast.parse(
        '"""plan_coverage in documentation only."""\n'
        "status = {'plan_migration': 'shadow'}\n"
        "from app.services.learning.plan_service import LearningPlanService\n"
    )
    assert not _sidecar_references(inert, REQUIRED)


def test_audit_detects_side_effects_but_allows_read_only_source() -> None:
    unsafe = ast.parse(
        "from app.services.grounding import corpus_fixtures\n"
        "importlib.import_module('app.services.grounding.corpus_service')\n"
        "import httpx\n"
        "conn.execute('UPDATE learning_plans SET active = true')\n"
        "conn.commit()\n"
        "@router.post('/plan-proposal')\n"
        "def activate(): pass\n"
        "if __name__ == '__main__': activate()\n"
    )
    reasons = {reason for _, reason in _sidecar_violations(unsafe)}
    assert any(reason.startswith("operator/fixture import") for reason in reasons)
    assert any(reason.startswith("provider/network import") for reason in reasons)
    assert "mutation SQL" in reasons
    assert "write-capable call conn.commit" in reasons
    assert "automatic decorator router.post" in reasons
    assert "module CLI entrypoint" in reasons
    safe = ast.parse(
        "from app.services.grounding.coverage import CoverageReport\n"
        "cursor.execute('SELECT * FROM learning_plans WHERE id = %s')\n"
        "status = {'action': 'wait_for_release', 'proposal': 'shadow'}\n"
    )
    assert not _sidecar_violations(safe)


def test_public_routes_confirm_activation_worker_and_startup_do_not_wire_sidecar() -> None:
    owned = _sidecar_modules()
    runtime = [
        *sorted((APP_DIR / "routes").glob("*.py")),
        APP_DIR / "main.py",
        LEARNING_DIR / "__init__.py",
        *(LEARNING_DIR / f"{name}.py" for name in (
            "plan_service", "plan_repository", "track_service", "track_repository",
        )),
        *sorted(WORKER_DIR.rglob("*.py")),
    ]
    assert runtime and all(path.is_file() for path in runtime), "runtime inventory missing"
    references = [
        f"{path}:{line}: {value}"
        for path in runtime
        for line, value in _sidecar_references(_parse(path), owned)
    ]
    assert not references, "phase-I sidecar reached public/activation path:\n" + "\n".join(references)
    assert START_DEV.is_file(), "startup inventory missing"
    startup_reference = re.compile(r"\b(?:" + "|".join(sorted(owned)) + r")\b")
    startup = [
        f"{START_DEV}:{line}: {text.strip()}"
        for line, text in enumerate(START_DEV.read_text(encoding="utf-8").splitlines(), 1)
        if not text.lstrip().startswith("#") and startup_reference.search(text)
    ]
    assert not startup, "phase-I startup reference:\n" + "\n".join(startup)


def test_new_sidecar_modules_remain_read_only_offline_and_without_entrypoints() -> None:
    owned = _sidecar_modules()
    violations = [
        f"{path}:{line}: {reason}"
        for name in sorted(owned)
        for path in [LEARNING_DIR / f"{name}.py"]
        for line, reason in _sidecar_violations(_parse(path))
    ]
    assert not violations, "phase-I sidecar acquired mutation/IO/entrypoint:\n" + "\n".join(
        violations
    )

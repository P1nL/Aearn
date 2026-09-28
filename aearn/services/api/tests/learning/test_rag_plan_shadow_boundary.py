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

# D is a distinct, default-off internal consumer. It does not become a phase-I
# read-only sidecar merely because planning reuses that package's draft authority.
D_GROUNDING_MODULES = frozenset({
    "material_contracts_v2", "evidence_binding_v2", "current_authorization",
    "material_binding_repository",
})
D_LEARNING_MODULES = frozenset({"material_selection", "material_planning_composition",
                               "material_semantics"})
D_GROUNDING_OWNER = "app.services.grounding"


def _d_imports(tree: ast.Module, path: Path) -> list[tuple[int, str, str | None]]:
    """Report imported symbols separately from actual module-wide access."""
    references: list[tuple[int, str, str | None]] = []
    imported_names: list[tuple[int, str]] = []
    try:
        package_parts = ["app", *path.resolve().relative_to(APP_DIR.resolve()).parts[:-1]]
    except ValueError:
        package_parts = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                if not package_parts or node.level > len(package_parts):
                    continue
                parent = package_parts[:len(package_parts) - node.level + 1]
                base = ".".join((*parent, base)).rstrip(".")
            # Do not emit a synthetic base-module reference for a symbol import.
            # `from package import module` still resolves to an actual module
            # reference below, as do Import and literal dynamic imports.
            imported_names.extend((node.lineno, f"{base}.{alias.name}")
                                  for alias in node.names)
        elif isinstance(node, ast.Call) and _dotted(node.func) in LOADERS and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                imported_names.append((node.lineno, first.value))
    for line, imported in imported_names:
        for package, names in ((D_GROUNDING_OWNER, D_GROUNDING_MODULES),
                               (PACKAGE, D_LEARNING_MODULES)):
            for module in names:
                full = f"{package}.{module}"
                if imported == full or imported.startswith(full + "."):
                    symbol = imported[len(full) + 1:] if imported != full else None
                    references.append((line, full, symbol))
    return references


def _d_allowed(path: Path, module: str, symbol: str | None) -> bool:
    path = path.resolve()
    if path.parent == (APP_DIR / "services" / "grounding").resolve():
        # Only D's own files may depend on its D sibling modules. No B/C source
        # actor may reverse-import a planning consumer to confer authority.
        return path.stem in D_GROUNDING_MODULES and module.startswith(D_GROUNDING_OWNER + ".")
    internal = (LEARNING_DIR / path.name).resolve() == path
    if internal and path.stem == "material_semantics":
        # A probabilistic reviewer may read the strict snapshot/hash contract,
        # never call source authorization or publication authority directly.
        return (module == f"{D_GROUNDING_OWNER}.material_contracts_v2"
                and symbol in {"digest", "MaterialSelectionResult"})
    if internal and path.stem in D_LEARNING_MODULES:
        return True
    # These two integration files may map only the named safe exceptions. No
    # module import (symbol=None), wildcard, resolver or authority class is granted.
    exception_consumers = {
        (LEARNING_DIR / "plan_capability.py").resolve(),
        (APP_DIR / "services" / "tutor" / "interactive.py").resolve(),
    }
    exceptions = {
        f"{D_GROUNDING_OWNER}.material_binding_repository": "MaterialBindingConflict",
        f"{D_GROUNDING_OWNER}.current_authorization": "EvidenceDenied",
    }
    if path in exception_consumers and module in exceptions:
        return symbol == exceptions[module]
    if path == (APP_DIR / "services" / "tutor" / "interactive.py").resolve():
        return (module == f"{PACKAGE}.material_selection"
                and symbol == "PostgresMaterialPlanningConsumer")
    if internal and path.stem == "plan_capability":
        return (module == f"{PACKAGE}.material_selection"
                and symbol in {"PostgresMaterialPlanningConsumer", "material_transaction"})
    return False


def test_d_import_audit_detects_forbidden_routes_workers_and_source_reverse_imports() -> None:
    samples = (
        (APP_DIR / "routes" / "learning.py",
         "from app.services.grounding.evidence_binding_v2 import EvidenceSelection\n"),
        (WORKER_DIR / "worker_app.py",
         "import app.services.learning.material_selection\n"),
        (APP_DIR / "services" / "grounding" / "autonomous" / "source_policy.py",
         "from ..material_binding_repository import MaterialBindingRepository\n"),
    )
    for path, source in samples:
        refs = _d_imports(ast.parse(source), path)
        assert refs and any(not _d_allowed(path, module, symbol)
                            for _, module, symbol in refs)
    allowed_path = LEARNING_DIR / "material_selection.py"
    assert _d_allowed(allowed_path, f"{D_GROUNDING_OWNER}.evidence_binding_v2",
                      "EvidenceSelection")
    assert not _d_imports(ast.parse("# evidence_binding_v2 in comment\npass\n"), allowed_path)


def test_d_exception_imports_do_not_grant_module_or_authority_access() -> None:
    paths = (LEARNING_DIR / "plan_capability.py",
             APP_DIR / "services" / "tutor" / "interactive.py")
    for path in paths:
        for module, exception in (
            ("current_authorization", "EvidenceDenied"),
            ("material_binding_repository", "MaterialBindingConflict"),
        ):
            full = f"{D_GROUNDING_OWNER}.{module}"
            for source in (
                f"from {full} import {exception} as SafeError",
                f"from ..grounding.{module} import {exception}",
            ):
                refs = _d_imports(ast.parse(source), path)
                assert refs == [(1, full, exception)]
                assert all(_d_allowed(path, name, symbol) for _, name, symbol in refs)
            unsafe_sources = (
                f"import {full} as authority\nauthority.resolve_evidence()",
                f"from {D_GROUNDING_OWNER} import {module} as authority\n"
                "authority.check_current_authorization()",
                f"from ..grounding import {module} as authority\n"
                "authority.assert_publication_fence()",
                f"authority = importlib.import_module('{full}')\n"
                "authority.authorize_binding()",
                f"from {full} import *",
                f"from {full} import {exception}, resolve_evidence\nresolve_evidence()",
                f"from {full} import check_current_authorization\ncheck_current_authorization()",
                f"from {full} import assert_publication_fence\nassert_publication_fence()",
                f"from {full} import authorize_binding\nauthorize_binding()",
                f"from {full} import CurrentAuthorization",
                f"from {full} import PostgresMaterialBindingRepository",
            )
            for source in unsafe_sources:
                refs = _d_imports(ast.parse(source), path)
                assert refs and any(not _d_allowed(path, name, symbol)
                                    for _, name, symbol in refs), source
            # The exception allowlist is file-scoped, not a learning/tutor grant.
            for other in (LEARNING_DIR / "plan_service.py",
                          APP_DIR / "services" / "tutor" / "context.py"):
                assert not _d_allowed(other, full, exception)


def test_semantic_reviewer_only_reads_material_contract_symbols() -> None:
    path = LEARNING_DIR / "material_semantics.py"
    contract = f"{D_GROUNDING_OWNER}.material_contracts_v2"
    assert _d_allowed(path, contract, "digest")
    assert _d_allowed(path, contract, "MaterialSelectionResult")
    for symbol in (None, "*", "CurrentMaterialAuthorizationReceipt", "EvidenceBindingV2"):
        assert not _d_allowed(path, contract, symbol)
    assert not _d_allowed(path, f"{D_GROUNDING_OWNER}.current_authorization", "CurrentAuthorization")


def test_d_modules_have_only_exact_internal_import_consumers() -> None:
    assert all((APP_DIR / "services" / "grounding" / f"{name}.py").is_file()
               for name in D_GROUNDING_MODULES)
    roots = (APP_DIR, WORKER_DIR)
    violations = [
        f"{path}:{line}: {module}{'.' + symbol if symbol else ''}"
        for root in roots for path in sorted(root.rglob("*.py"))
        for line, module, symbol in _d_imports(_parse(path), path)
        if not _d_allowed(path, module, symbol)
    ]
    assert not violations, "D authority imported outside exact internal seams:\n" + "\n".join(violations)
    startup = START_DEV.read_text(encoding="utf-8").splitlines()
    assert not [line for line in startup if not line.lstrip().startswith("#")
                and any(name in line for name in D_GROUNDING_MODULES | D_LEARNING_MODULES)]

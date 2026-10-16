"""Default-off safe phase failure coordinates; observation is never authority.

No raw exception/context/message/body, private IDs, DB, file IO, logger or retry.
Failure of the observer cannot change the original UNKNOWN/deny/settlement.
"""
from __future__ import annotations
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import re
from typing import Literal

_MODULES = frozenset({"persistent_pack", "persistent_pack_pipeline", "persistent_pack_candidate", "shared_review",
    "shared_continuation", "shared_validation", "native_review_investigation", "native_revision", "native_revision_recheck",
    "native_normal_revision_readmission", "shared_admission_facts", "repository", "runtime", "runtime_repository",
    "budget_repository", "pipeline_repository", "native_type_evidence", "native_relation_review"})
_CLASSES = frozenset({"ValueError", "TypeError", "KeyError", "AttributeError", "ValidationError", "PipelineRepositoryError",
    "PersistentPackPending", "CheckViolation", "NotNullViolation", "ForeignKeyViolation", "UniqueViolation",
    "UndefinedFunction", "UndefinedColumn", "UndefinedTable", "SyntaxError", "InvalidTextRepresentation",
    "InFailedSqlTransaction", "LockNotAvailable", "DeadlockDetected", "SerializationFailure", "QueryCanceled",
    "OperationalError", "InterfaceError"})
_SQLSTATES = frozenset({"23514", "23502", "23503", "23505", "42883", "42703", "42P01", "42601", "22P02", "25P02",
    "55P03", "40P01", "40001", "57014"})
_PG_FUNCTIONS = frozenset({"enforce_shared_review_investigation_insert", "assert_persistent_normal_repair",
    "assert_persistent_pack_phase", "enforce_persistent_pack_journal", "enforce_item_supply_shared_candidate_continuation",
    "public_native_source_current", "public_normal_mapping_current", "private_native_mapping_current",
    "rag_actual_d_private_epoch", "deny_revision_admission_without_discharge", "enforce_shared_native_revision_insert",
    "enforce_shared_revision_recheck_insert"})
_PREFIX = "app.services.learning.item_supply."

@dataclass(frozen=True)
class PhaseFailureCoordinate:
    module: str
    function: str
    line: int

@dataclass(frozen=True)
class PhaseFailureObservation:
    operation: Literal["run_phase", "preparation_probe"]
    exception_class: str
    sqlstate: str | None
    python_coordinates: tuple[PhaseFailureCoordinate, ...]
    pg_function: str | None
    pg_line: int | None
    # A coordinate is not a provider receipt, no-dispatch attestation or grant.
    paid_dispatch_asserted: None = None

@dataclass
class PersistentPackDiagnostics:
    observations: list[PhaseFailureObservation] = field(default_factory=list)
    diagnostic_unavailable: bool = False

_ACTIVE: ContextVar[PersistentPackDiagnostics | None] = ContextVar("persistent_pack_diagnostics", default=None)

@contextmanager
def collect_persistent_pack_diagnostics() -> Iterator[PersistentPackDiagnostics]:
    collector = PersistentPackDiagnostics()
    token = _ACTIVE.set(collector)
    try:
        yield collector
    finally:
        _ACTIVE.reset(token)


def observe_persistent_pack_failure(exc: BaseException, *, operation: Literal["run_phase", "preparation_probe"]="run_phase") -> None:
    collector = _ACTIVE.get()
    if collector is None:
        return
    try:
        if operation not in {"run_phase", "preparation_probe"}:
            collector.diagnostic_unavailable = True
            return
        if len(collector.observations) >= 8:
            return
        raw_class = type(exc).__name__
        klass = raw_class if raw_class in _CLASSES else "UnknownException"
        state = getattr(exc, "sqlstate", None)
        state = state if isinstance(state, str) and state in _SQLSTATES else None
        coordinates: list[PhaseFailureCoordinate] = []
        tb = exc.__traceback__
        while tb is not None:
            name = tb.tb_frame.f_globals.get("__name__", "")
            module = name.removeprefix(_PREFIX) if isinstance(name,str) and name.startswith(_PREFIX) else ""
            function = tb.tb_frame.f_code.co_name
            if module in _MODULES and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,79}", function) and len(coordinates) < 8:
                coordinates.append(PhaseFailureCoordinate(module, function, tb.tb_lineno))
            tb = tb.tb_next
        pg_function,pg_line = None,None
        context = getattr(getattr(exc,"diag",None),"context",None)
        if isinstance(context,str):
            for match in re.finditer(r"PL/pgSQL function (?:[a-z_]+\.)?([a-z_][a-z_0-9]*)\([^\n]*?\) line ([0-9]+) at",context):
                function,line = match.group(1),int(match.group(2))
                if function in _PG_FUNCTIONS and 0 < line <= 100000:
                    pg_function,pg_line = function,line
                    break
        collector.observations.append(PhaseFailureObservation(operation,klass,state,tuple(coordinates),pg_function,pg_line))
    except Exception:
        collector.diagnostic_unavailable = True

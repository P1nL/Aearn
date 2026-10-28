"""Closed fresh source oracles. No candidate, network or host execution."""
from __future__ import annotations

import hashlib
import html
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from aearn_shared.execution import ExecutionAction, SandboxInputV1
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.sandbox.execution_contracts import RunnerPort, RunnerTerminalReceipt

from .assessment_contracts import ExecutionScope
from .actual_d_finite_source import ACTUAL_D_PROFILE_TARGET, ACTUAL_D_STORAGE_PROFILE, ActualDFiniteSourceScope
from .contracts import FrozenContract, HANDLE, HASH, LearningMaterialDemand, RagBudgetDelegation, revalidate
from .material_lifetime import COURSE_MATERIAL_POLICY, LEGACY_MATERIAL_POLICY, MaterialLifetimePolicy, material_lifetime
from .source_review_repository import CompleteCapture
from .sqlite_select_automated_review import WHERE_PARAGRAPH, _Parser

if TYPE_CHECKING:
    from .sqlite_predicate_source_profile import _SQLiteAnalysisData

DOMAIN = b"AEARN-RAG-FRESH-ASSESSMENT-SOURCE-V1\n"
COURSE_DOMAIN = b"AEARN-RAG-FRESH-COURSE-ASSESSMENT-SOURCE-V2\n"
ACTUAL_D_DOMAIN = b"AEARN-RAG-ACTUAL-D-FINITE-SOURCE-V3\n"
SourceProofFormat = Literal["aearn.rag.fresh-assessment-source.v1", "aearn.rag.fresh-assessment-source.v2", "aearn.rag.actual-d-finite-source.v3"]
ACTOR = "service.rag-assessment"
PROBE_NAME = "source_assessment_oracle"
ACTUAL_D_PROBE_NAME = "actual_d_finite_source_oracle"
PYTHON_PROFILE_IDS = ("python-sum-print-source-v1", "python-sum-print-source-v2")
PUBLIC_PYTHON_PROFILES = ("python-state-source-v1", "python-binding-source-v1")
PROFILE_IDS = ("python-sum-print-source-v1", "sqlite-filter-order-source-v1", "python-sum-print-source-v2", *PUBLIC_PYTHON_PROFILES, "sqlite-predicate-source-v1", *ACTUAL_D_PROFILE_TARGET)
ProfileId = Literal["python-sum-print-source-v1", "sqlite-filter-order-source-v1", "python-sum-print-source-v2", "python-state-source-v1", "python-binding-source-v1", "sqlite-predicate-source-v1", "python-state-actual-d-source-v1", "python-binding-actual-d-source-v1", "sqlite-predicate-actual-d-source-v1"]
PYTHON_STATEMENTS_URL = "https://docs.python.org/3/reference/simple_stmts.html"
PYTHON_BINDING = "Assignment statements are used to (re)bind names to values and to modify attributes or items of mutable objects:"
PYTHON_RHS = "An assignment statement evaluates the expression list (remember that this can be a single expression or a comma-separated list, the latter yielding a tuple) and assigns the single resulting object to each of the target lists, from left to right."
PYTHON_AUGMENTED = "An augmented assignment evaluates the target (which, unlike normal assignment statements, cannot be an unpacking) and the expression list, performs the binary operation specific to the type of assignment on the two operands, and assigns the result to the original target. The target is only evaluated once."
PYTHON_URL = "https://docs.python.org/3/library/functions.html"
PYTHON_CANONICAL_URL = "https://docs.python.org/3/builtins/functions.html"
SQLITE_URL = "https://www.sqlite.org/lang_select.html"
PYTHON_SUM = "Sums start and the items of an iterable from left to right and returns the total."
PYTHON_PRINT = "Print objects to the text stream file, separated by sep and followed by end."
SQLITE_ORDER = "If a SELECT statement does have an ORDER BY clause, then the list of expressions attached to the ORDER BY determine the order in which rows are returned to the user."
SQLITE_ORDER_PARAGRAPH = (
    "If a SELECT statement that returns more than one row does not have an ORDER BY clause, "
    "the order in which the rows are returned is undefined. Or, if a SELECT statement does have "
    "an ORDER BY clause, then the list of expressions attached to the ORDER BY determine the "
    "order in which rows are returned to the user. If all ORDER BY expressions evaluate to "
    "equal values, the order in which the rows are returned is undefined."
)
# Exact complete visible paragraph observed in the real official capture.
SQLITE_ORDER_TWO_SENTENCE_PARAGRAPH = (
    "If a SELECT statement that returns more than one row does not have an ORDER BY clause, "
    "the order in which the rows are returned is undefined. Or, if a SELECT statement does have "
    "an ORDER BY clause, then the list of expressions attached to the ORDER BY determine the "
    "order in which rows are returned to the user."
)
# Official SQLite page deliberately omits only the final div/body/html closures.
# This exact footer is a finite wrapper exception, not a truncation repair.
SQLITE_OFFICIAL_UNCLOSED_FOOTER = (
    '<p align="center"><small><i>This page was last updated on 2026-01-26 15:45:07Z </small></i></p>\r\n\r\n'
)
SQLITE_OFFICIAL_UNCLOSED_FOOTERS = (
    SQLITE_OFFICIAL_UNCLOSED_FOOTER,
    SQLITE_OFFICIAL_UNCLOSED_FOOTER.replace("\r\n\r\n", "\n\n"),
)
PYTHON_SUM_PARAGRAPH = PYTHON_SUM + " The iterable’s items are normally numbers, and the start value is not allowed to be a string."
PYTHON_PRINT_PARAGRAPH = PYTHON_PRINT + " sep, end, file, and flush, if present, must be given as keyword arguments."


class SourceAssessmentDenied(ValueError):
    """Bounded refusal, never raw source or terminal text."""


class SourceSpan(FrozenContract):
    unit: str = Field(pattern=HANDLE)
    start_byte: int = Field(ge=0, le=8_388_608)
    end_byte: int = Field(gt=0, le=8_388_608)
    sha256: str = Field(pattern=HASH)


class _Units(_Parser):
    """Reuse the safe complete visible-unit HTML parser, with finite assertions."""

    def __init__(self, source: str, statements: dict[str, tuple[str, ...]]) -> None:
        super().__init__(source)
        self.statements = statements
        self.approved_units_explicitly_closed = True
        self._explicit_unit_end = False

    def handle_endtag(self, tag: str) -> None:
        self._explicit_unit_end = tag in ("p", "li") and tag in self.stack
        try:
            super().handle_endtag(tag)
        finally:
            self._explicit_unit_end = False

    def _finish_unit(self) -> None:
        if self.unit:
            normalized = " ".join(html.unescape("".join(p[0] for p in self.unit)).split())
            for unit, statements in self.statements.items():
                # Never extract a sub-sentence from a contradicting/quoted paragraph.
                if normalized in statements:
                    if self.unit_unsafe:
                        self.invalid = True
                    else:
                        if not self._explicit_unit_end:
                            self.approved_units_explicitly_closed = False
                        self.spans.append((unit, self.unit[0][1], self.unit[-1][2]))
        self.unit = None
        self.unit_unsafe = False


def analyze_source(capture: CompleteCapture, profile_id: ProfileId, *,
                   _sqlite_data: _SQLiteAnalysisData | None = None) -> tuple[SourceSpan, ...]:
    if profile_id in ("sqlite-predicate-source-v1", "sqlite-predicate-actual-d-source-v1"):
        from .sqlite_predicate_source_profile import _analyze_sqlite_capture

        return _analyze_sqlite_capture(capture, "select", data=_sqlite_data)
    if (type(capture) is not CompleteCapture or capture.lane != "registered"
            or capture.origin != "official" or not 0 < len(capture.body) <= 8_388_608
            or capture.digest != hashlib.sha256(capture.body).hexdigest()
            or capture.revision != capture.digest or profile_id not in PROFILE_IDS):
        raise SourceAssessmentDenied("SOURCE_PROFILE_DENIED")
    if profile_id in (*PUBLIC_PYTHON_PROFILES, "python-state-actual-d-source-v1", "python-binding-actual-d-source-v1"):
        url, subject, facets = PYTHON_STATEMENTS_URL, "route.python", ("fundamentals",)
        statements: dict[str, tuple[str, ...]] = {"claim.binding": (PYTHON_BINDING,), "claim.rhs": (PYTHON_RHS,)}
        if profile_id in ("python-state-source-v1", "python-state-actual-d-source-v1"):
            statements["claim.augmented"] = (PYTHON_AUGMENTED,)
    elif profile_id in PYTHON_PROFILE_IDS:
        url = PYTHON_CANONICAL_URL if profile_id == "python-sum-print-source-v2" else PYTHON_URL
        subject, facets = "route.python", ("fundamentals",)
        statements = {"claim.sum": (PYTHON_SUM, PYTHON_SUM_PARAGRAPH),
                      "claim.print": (PYTHON_PRINT, PYTHON_PRINT_PARAGRAPH)}
    else:
        url, subject, facets = SQLITE_URL, "route.sql", ("queries",)
        statements = {"claim.where": (WHERE_PARAGRAPH,),
                      "claim.order": (SQLITE_ORDER, SQLITE_ORDER_PARAGRAPH, SQLITE_ORDER_TWO_SENTENCE_PARAGRAPH)}
    if (capture.final_url != url or capture.request_chain != (url,)
            or capture.scope.subject_id != subject or capture.scope.facets != facets):
        raise SourceAssessmentDenied("SOURCE_PROFILE_DENIED")
    text = capture.body.decode("utf-8")
    parser = _Units(text, statements)
    parser.feed(text)
    parser.close()
    complete_wrappers = parser.closed_html and not parser.stack
    official_sqlite_wrappers = (
        profile_id == "sqlite-filter-order-source-v1"
        and not parser.closed_html and parser.stack == ["html", "body", "div"]
        and parser.unit is None and not parser.unit_unsafe
        and parser.approved_units_explicitly_closed
        and text.endswith(tuple("</p>" + footer for footer in SQLITE_OFFICIAL_UNCLOSED_FOOTERS))
    )
    if (parser.invalid or parser.html_count != 1 or parser.body_count != 1
            or not (complete_wrappers or official_sqlite_wrappers)
            or {x[0] for x in parser.spans} != set(statements)
            or len(parser.spans) != len(statements)):
        raise SourceAssessmentDenied("SOURCE_ASSERTIONS_UNSUPPORTED")
    spans = []
    for unit, start, end in parser.spans:
        lo, hi = len(text[:start].encode()), len(text[:end].encode())
        if not 0 < hi - lo <= 4096:
            raise SourceAssessmentDenied("SOURCE_EXCERPT_BOUND")
        spans.append(SourceSpan(unit=unit, start_byte=lo, end_byte=hi,
                                sha256=hashlib.sha256(capture.body[lo:hi]).hexdigest()))
    return tuple(spans)


def source_request(profile_id: ProfileId) -> tuple[SandboxInputV1, dict[str, Any], str]:
    if profile_id in ACTUAL_D_PROFILE_TARGET:
        from .finite_course_source_oracle import public_course_source_request

        # Same independent finite semantic declaration, NEW scope/run/proof.
        return public_course_source_request(ACTUAL_D_PROFILE_TARGET[profile_id])
    if profile_id == "sqlite-predicate-source-v1":
        from .finite_course_source_oracle import public_course_source_request

        return public_course_source_request("sqlite-predicate-order-v1")
    if profile_id in PUBLIC_PYTHON_PROFILES:
        from .finite_course_source_oracle import public_course_source_request

        return public_course_source_request("python-state-update-v1" if profile_id == "python-state-source-v1" else "python-kc-binding-v1")
    if profile_id in PYTHON_PROFILE_IDS:
        code = "numbers = [3, -1, 0, 3]\nprint(sum(numbers))\n"
        runtime = "python-stdout-v1"
        cases: list[dict[str, Any]] = [{"id": "source_oracle", "case_type": "visible"}]
        expected: dict[str, Any] = {"cases": [{"id": "source_oracle", "status": "success",
                              "code": "python_terminal", "stdout": "5\n"}]}
        applicability = "Finite signed Linux CPython sum/print integer-list stdout profile; not arbitrary Python or latest-version approval."
    elif profile_id == "sqlite-filter-order-source-v1":
        code = "SELECT id, name FROM learners WHERE track = 'sql' ORDER BY id"
        runtime = "sqlite-query-v1"
        cases = [{"id": "source_oracle", "case_type": "visible", "max_rows": 20,
                  "tables": [{"name": "learners", "columns": [
                      {"name": "id", "data_type": "INTEGER", "nullable": False},
                      {"name": "name", "data_type": "TEXT", "nullable": False},
                      {"name": "track", "data_type": "TEXT", "nullable": True}]}],
                  "dataset": {"tables": [{"table": "learners", "rows": [
                      [9, "Ada", "sql"], [5, "Bea", "python"], [2, "Zoe", "sql"],
                      [1, "Nil", None], [4, "Ada", "sql"]]}]}}]
        expected = {"cases": [{"id": "source_oracle", "status": "success",
                              "code": "sqlite_terminal", "columns": ["id", "name"],
                              "rows": [[2, "Zoe"], [4, "Ada"], [9, "Ada"]]}]}
        applicability = "Finite pinned SQLite SELECT track=sql and integer id ORDER BY profile with TEXT, NULL and duplicate names; not PostgreSQL or arbitrary SQL."
    else:
        raise SourceAssessmentDenied("SOURCE_PROFILE_DENIED")
    request = SandboxInputV1(runtime_id=runtime, action=ExecutionAction.TEST, submission=code,
        visible_test_bundle_json=json.dumps(cases, separators=(",", ":")),
        source_reference_hash=canonical_hash({"profile": profile_id, "code": code}),
        test_reference_hash=canonical_hash(cases))
    return request, expected, applicability


class PreparedSourceAssessment(FrozenContract):
    profile_id: ProfileId
    capture_id: UUID
    source_handle: str = Field(pattern=HANDLE)
    document_handle: str = Field(pattern=HANDLE)
    document_hash: str = Field(pattern=HASH)
    license_id: str
    origin: Literal["official"] = "official"
    reading_level: Literal["beginner", "intermediate", "advanced"]
    provenance_digest: str = Field(pattern=HASH)
    policy_id: str = Field(pattern=HANDLE)
    policy_generation: int = Field(ge=1)
    budget: RagBudgetDelegation
    storage_receipt_id: str = Field(pattern=HANDLE)
    demand: LearningMaterialDemand
    spans: tuple[SourceSpan, ...] = Field(min_length=2, max_length=5)
    prepared_at: datetime
    authority_expires_at: datetime

    @model_validator(mode="after")
    def bounded(self) -> PreparedSourceAssessment:
        python = self.profile_id in (*PYTHON_PROFILE_IDS, *PUBLIC_PYTHON_PROFILES, "python-state-actual-d-source-v1", "python-binding-actual-d-source-v1")
        if (self.demand.purpose != "assessment_evidence"
                or self.demand.scope.facets != (("fundamentals",) if python else ("queries",))
                or self.demand.scope.subject_id != ("route.python" if python else "route.sql")
                or len(self.spans) != (5 if self.profile_id in ("sqlite-predicate-source-v1", "sqlite-predicate-actual-d-source-v1")
                                       else 3 if self.profile_id in ("python-state-source-v1", "python-state-actual-d-source-v1") else 2)
                or self.prepared_at.tzinfo is None or self.prepared_at.utcoffset() != timedelta(0)
                or self.authority_expires_at.tzinfo is None
                or not self.prepared_at < self.authority_expires_at <= self.budget.expires_at):
            raise ValueError("invalid fresh authority")
        if self.profile_id == "sqlite-predicate-source-v1":
            if type(self) is not PreparedSQLiteSourceAssessment:
                raise ValueError("native SQLite companions required")
            from app.services.grounding.public_course_contracts import public_course_demand

            if self.demand != public_course_demand("sqlite-predicate-order-v1"):
                raise ValueError("public course demand mismatch")
        if self.profile_id in PUBLIC_PYTHON_PROFILES:
            from app.services.grounding.public_course_contracts import public_course_demand

            expected = public_course_demand("python-state-update-v1" if self.profile_id == "python-state-source-v1" else "python-kc-binding-v1")
            if self.demand != expected:
                raise ValueError("public course demand mismatch")
        if self.profile_id in ACTUAL_D_PROFILE_TARGET and type(self) not in (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment):
            raise ValueError("actual D scope required")
        return self

    @property
    def consume_actor(self) -> str:
        # Derived, not a new serialized default: historical signed bytes are unchanged.
        return "service.rag-public-course" if self.profile_id in (*PUBLIC_PYTHON_PROFILES, "sqlite-predicate-source-v1") else ACTOR

    @property
    def execution_scope(self) -> ExecutionScope:
        if self.profile_id in ACTUAL_D_PROFILE_TARGET:
            from .finite_course_source_oracle import public_course_execution_scope

            return public_course_execution_scope(ACTUAL_D_PROFILE_TARGET[self.profile_id])
        if self.profile_id == "sqlite-predicate-source-v1":
            from .finite_course_source_oracle import public_course_execution_scope

            return public_course_execution_scope("sqlite-predicate-order-v1")
        if self.profile_id in PUBLIC_PYTHON_PROFILES:
            from .finite_course_source_oracle import public_course_execution_scope

            return public_course_execution_scope("python-state-update-v1" if self.profile_id == "python-state-source-v1" else "python-kc-binding-v1")
        request, expected, applicability = source_request(self.profile_id)
        return ExecutionScope(runtime_profile=request.runtime_id,
            input_hash=canonical_hash(request.model_dump(mode="json")),
            semantics_hash=canonical_hash({"expected": expected, "applicability": applicability}))

    @property
    def claim_hash(self) -> str:
        return canonical_hash({"profile": self.profile_id, "spans": [s.model_dump() for s in self.spans],
                               "execution_scope": self.execution_scope.model_dump(),
                               "document_hash": self.document_hash})


class SQLiteCompanionCapture(FrozenContract):
    role: Literal["expression", "corefunc"]
    capture_id: UUID
    source_handle: str = Field(pattern=HANDLE)
    document_hash: str = Field(pattern=HASH)
    provenance_digest: str = Field(pattern=HASH)
    policy_id: str = Field(pattern=HANDLE)
    policy_generation: int = Field(ge=1)
    budget: RagBudgetDelegation
    storage_receipt_id: str = Field(pattern=HANDLE)
    license_id: str
    reading_level: Literal["beginner", "intermediate", "advanced"]
    spans: tuple[SourceSpan, ...] = Field(min_length=1, max_length=4)
    authority_expires_at: datetime

    @model_validator(mode="after")
    def bounded(self) -> SQLiteCompanionCapture:
        expected = ({"claim.arithmetic", "claim.null", "claim.null-boolean", "claim.boolean"}
                    if self.role == "expression" else {"claim.coalesce"})
        if ({span.unit for span in self.spans} != expected or len(self.spans) != len(expected)
                or self.authority_expires_at.tzinfo is None
                or self.authority_expires_at.utcoffset() != timedelta(0)
                or self.budget.expires_at != self.authority_expires_at):
            raise ValueError("invalid SQLite companion")
        return self


class PreparedSQLiteSourceAssessment(PreparedSourceAssessment):
    """A new typed signed shape; no optional fields added to historical proofs."""

    companions: tuple[SQLiteCompanionCapture, SQLiteCompanionCapture]

    @model_validator(mode="after")
    def sqlite_bound(self) -> PreparedSQLiteSourceAssessment:
        if (self.profile_id not in ("sqlite-predicate-source-v1", "sqlite-predicate-actual-d-source-v1")
                or tuple(c.role for c in self.companions) != ("expression", "corefunc")
                or len({self.capture_id, *(c.capture_id for c in self.companions)}) != 3
                or any(not self.prepared_at < self.authority_expires_at <= c.authority_expires_at
                       for c in self.companions)):
            raise ValueError("invalid SQLite capture composition")
        return self

    @property
    def claim_hash(self) -> str:
        return canonical_hash({"primary_claim_hash": super().claim_hash,
                               "companions": [c.model_dump(mode="json") for c in self.companions]})


class PreparedActualDSourceAssessment(PreparedSourceAssessment):
    actual_d: ActualDFiniteSourceScope

    @model_validator(mode="after")
    def actual_scope(self) -> PreparedActualDSourceAssessment:
        _check_actual_d(self, self.actual_d)
        if self.profile_id == "sqlite-predicate-actual-d-source-v1":
            raise ValueError("actual D SQLite companions required")
        return self

    @property
    def claim_hash(self) -> str:
        return canonical_hash({"source_claim": super().claim_hash, "actual_d": self.actual_d.model_dump(mode="json")})


class PreparedActualDSQLiteSourceAssessment(PreparedSQLiteSourceAssessment):
    actual_d: ActualDFiniteSourceScope

    @model_validator(mode="after")
    def actual_scope(self) -> PreparedActualDSQLiteSourceAssessment:
        _check_actual_d(self, self.actual_d)
        if self.profile_id != "sqlite-predicate-actual-d-source-v1":
            raise ValueError("actual D SQLite profile required")
        return self

    @property
    def claim_hash(self) -> str:
        return canonical_hash({"source_claim": super().claim_hash, "actual_d": self.actual_d.model_dump(mode="json")})


def _check_actual_d(prepared: PreparedSourceAssessment, scope: ActualDFiniteSourceScope) -> None:
    scope = revalidate(scope, ActualDFiniteSourceScope)
    if (ACTUAL_D_PROFILE_TARGET.get(prepared.profile_id) != scope.target_id
            or prepared.demand.plan_ref != "draft." + scope.draft.draft_id
            or prepared.demand.node_ref != "node." + scope.node_id
            or prepared.demand.draft_revision != scope.draft.draft_version):
        raise ValueError("actual D finite demand mismatch")


def storage_profile_id(prepared: PreparedSourceAssessment) -> str:
    """Legacy SQL column is a semantic key; signed profile is NEVER rewritten."""
    return ACTUAL_D_STORAGE_PROFILE.get(prepared.profile_id, prepared.profile_id)


def revalidate_prepared(prepared: PreparedSourceAssessment) -> PreparedSourceAssessment:
    if type(prepared) is PreparedActualDSQLiteSourceAssessment:
        return revalidate(prepared, PreparedActualDSQLiteSourceAssessment)
    if type(prepared) is PreparedActualDSourceAssessment:
        return revalidate(prepared, PreparedActualDSourceAssessment)
    if type(prepared) is PreparedSQLiteSourceAssessment:
        return revalidate(prepared, PreparedSQLiteSourceAssessment)
    return revalidate(prepared, PreparedSourceAssessment)


@dataclass(frozen=True)
class SourceAssessmentRun:
    prepared: PreparedSourceAssessment
    terminal: RunnerTerminalReceipt


def _check_terminal(prepared: PreparedSourceAssessment, terminal: RunnerTerminalReceipt) -> None:
    request, expected, _ = source_request(prepared.profile_id)
    actual = prepared.actual_d if isinstance(prepared, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment)) else None
    if (terminal.mode != "live" or terminal.isolation != "approved_os_boundary"
            or terminal.probe_name != (ACTUAL_D_PROBE_NAME if actual else PROBE_NAME)
            or (actual is not None and terminal.run_id != actual.oracle_run_id)
            or terminal.request_hash != canonical_hash(request.model_dump(mode="json"))
            or len(terminal.lock_fingerprint) != 64 or not terminal.seal
            or not math.isfinite(terminal.elapsed_seconds) or not 0 <= terminal.elapsed_seconds <= 5
            or terminal.result.status.value != "success" or terminal.result.stderr
            or terminal.result.diagnostic_code != "item_supply_facts_v1"
            or terminal.result.test_feedback or terminal.result.passed_test_count or terminal.result.total_test_count
            or json.loads(terminal.result.stdout) != expected):
        raise SourceAssessmentDenied("SOURCE_TERMINAL_DENIED")


def run_source_assessment(prepared: PreparedSourceAssessment, *, runner: RunnerPort,
                          run_id: UUID) -> SourceAssessmentRun:
    prepared = revalidate_prepared(prepared)
    actual = prepared.actual_d if isinstance(prepared, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment)) else None
    if actual is not None and run_id != actual.oracle_run_id:
        raise SourceAssessmentDenied("SOURCE_ACTUAL_D_RUN_DENIED")
    request, _, _ = source_request(prepared.profile_id)
    terminal = runner.run(request=request, run_id=run_id, probe_name=ACTUAL_D_PROBE_NAME if actual else PROBE_NAME)
    if not runner.verify(terminal, request=request):
        raise SourceAssessmentDenied("SOURCE_SEAL_DENIED")
    _check_terminal(prepared, terminal)
    return SourceAssessmentRun(prepared, terminal)


class SourceAssessmentPayload(FrozenContract):
    format: SourceProofFormat = "aearn.rag.fresh-assessment-source.v1"
    prepared: PreparedActualDSQLiteSourceAssessment | PreparedActualDSourceAssessment | PreparedSQLiteSourceAssessment | PreparedSourceAssessment
    evidence_id: UUID
    review_id: UUID
    admission_id: UUID
    claim_id: UUID
    terminal: dict[str, Any]
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def bounded(self) -> SourceAssessmentPayload:
        actual = isinstance(self.prepared, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment))
        course = self.format != "aearn.rag.fresh-assessment-source.v1"
        lifetime = material_lifetime(COURSE_MATERIAL_POLICY if course else LEGACY_MATERIAL_POLICY)
        if (actual != (self.format == "aearn.rag.actual-d-finite-source.v3")
                or self.issued_at.tzinfo is None or self.issued_at.utcoffset() != timedelta(0)
                or self.expires_at.tzinfo is None or self.expires_at.utcoffset() != timedelta(0)
                or not self.prepared.prepared_at <= self.issued_at < self.expires_at
                or self.expires_at > self.prepared.authority_expires_at
                or self.expires_at - self.issued_at > lifetime
                or (course and (self.prepared.profile_id not in (*PUBLIC_PYTHON_PROFILES, "sqlite-predicate-source-v1", *ACTUAL_D_PROFILE_TARGET)
                    or self.prepared.authority_expires_at > self.prepared.prepared_at + lifetime
                    or (isinstance(self.prepared, PreparedSQLiteSourceAssessment)
                        and any(c.authority_expires_at > self.prepared.prepared_at + lifetime for c in self.prepared.companions))))):
            raise ValueError("invalid source receipt expiry")
        return self

    @property
    def execution_handle(self) -> str:
        return "source-execution." + self.evidence_id.hex

    @property
    def claim_handle(self) -> str:
        return "source-claim." + self.claim_id.hex

    @property
    def admission_handle(self) -> str:
        return "admission." + self.admission_id.hex


class SignedSourceAssessment(FrozenContract):
    service_key_id: str = Field(pattern=HANDLE)
    payload: SourceAssessmentPayload
    signature_hex: str = Field(pattern=r"^[0-9a-f]{128}$")


def canonical_source_payload(payload: SourceAssessmentPayload) -> bytes:
    p = revalidate(payload, SourceAssessmentPayload)
    domain = ACTUAL_D_DOMAIN if p.format == "aearn.rag.actual-d-finite-source.v3" else COURSE_DOMAIN if p.format == "aearn.rag.fresh-assessment-source.v2" else DOMAIN
    return domain + json.dumps(p.model_dump(mode="json"), sort_keys=True,
                               separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def source_proof_hash(receipt: SignedSourceAssessment) -> str:
    return canonical_hash(revalidate(receipt, SignedSourceAssessment).model_dump(mode="json"))


def sign_source_assessment(run: SourceAssessmentRun, *, runner: RunnerPort,
                           service_key_id: str, private_key: Ed25519PrivateKey,
                           now: datetime, expires_at: datetime | None = None,
                           lifetime_policy: MaterialLifetimePolicy | None = None) -> SignedSourceAssessment:
    if type(run) is not SourceAssessmentRun:
        raise SourceAssessmentDenied("SOURCE_RUN_DENIED")
    prepared = revalidate_prepared(run.prepared)
    actual = isinstance(prepared, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment))
    native_course = prepared.profile_id in (*PUBLIC_PYTHON_PROFILES, "sqlite-predicate-source-v1", *ACTUAL_D_PROFILE_TARGET)
    policy = lifetime_policy if lifetime_policy is not None else (COURSE_MATERIAL_POLICY if native_course else LEGACY_MATERIAL_POLICY)
    lifetime = material_lifetime(policy)
    if (policy == COURSE_MATERIAL_POLICY and not native_course) or (actual and policy != COURSE_MATERIAL_POLICY):
        raise SourceAssessmentDenied("SOURCE_LIFETIME_SCOPE_DENIED")
    request, _, _ = source_request(prepared.profile_id)
    if not runner.verify(run.terminal, request=request):
        raise SourceAssessmentDenied("SOURCE_SEAL_DENIED")
    _check_terminal(prepared, run.terminal)
    payload = SourceAssessmentPayload(
        format="aearn.rag.actual-d-finite-source.v3" if actual else "aearn.rag.fresh-assessment-source.v2" if policy == COURSE_MATERIAL_POLICY else "aearn.rag.fresh-assessment-source.v1",
        prepared=prepared, evidence_id=uuid4(), review_id=uuid4(),
        admission_id=uuid4(), claim_id=uuid4(), terminal=run.terminal.to_payload(),
        issued_at=now, expires_at=expires_at if expires_at is not None else min(prepared.authority_expires_at, now + lifetime))
    return SignedSourceAssessment(service_key_id=service_key_id, payload=payload,
        signature_hex=private_key.sign(canonical_source_payload(payload)).hex())


def verify_source_assessment(receipt: SignedSourceAssessment, *, service_keys: dict[str, bytes],
                             now: datetime) -> SourceAssessmentPayload:
    """Service signature attests previously checked real seal, never a caller flag."""
    try:
        signed = revalidate(receipt, SignedSourceAssessment)
        p = signed.payload
        key = Ed25519PublicKey.from_public_bytes(service_keys[signed.service_key_id])
        key.verify(bytes.fromhex(signed.signature_hex), canonical_source_payload(p))
        request, expected, _ = source_request(p.prepared.profile_id)
        terminal = p.terminal
        result = terminal["result"]
        actual = p.prepared.actual_d if isinstance(p.prepared, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment)) else None
        UUID(terminal["run_id"])
        if (not p.issued_at <= now < p.expires_at
                or set(terminal) != {"schema_version", "run_id", "probe_name", "request_hash",
                                    "lock_fingerprint", "result", "elapsed_seconds", "mode", "isolation", "seal"}
                or terminal["schema_version"] != "item_supply_runner_terminal_v1"
                or terminal["mode"] != "live" or terminal["isolation"] != "approved_os_boundary"
                or terminal["probe_name"] != (ACTUAL_D_PROBE_NAME if actual else PROBE_NAME)
                or (actual is not None and UUID(terminal["run_id"]) != actual.oracle_run_id)
                or terminal["request_hash"] != canonical_hash(request.model_dump(mode="json"))
                or len(terminal["lock_fingerprint"]) != 64 or not terminal["seal"]
                or not math.isfinite(terminal["elapsed_seconds"]) or not 0 <= terminal["elapsed_seconds"] <= 5
                or result["status"] != "success" or result["diagnostic_code"] != "item_supply_facts_v1"
                or result["stderr"] or result["test_feedback"]
                or result["passed_test_count"] or result["total_test_count"]
                or json.loads(result["stdout"]) != expected):
            raise ValueError("terminal mismatch")
        return p
    except Exception:
        raise SourceAssessmentDenied("SOURCE_PROOF_DENIED") from None

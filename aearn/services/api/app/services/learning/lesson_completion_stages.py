"""Opted-in Lesson stages. Private committed DATA is not publication authority."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from datetime import datetime
from threading import Event, Thread
from typing import cast

from app.core.config import get_settings
from app.agents.harness.contracts import TutorExecutionProfile
from app.db.connection import connect
from app.services.learning import lesson_authoring as authoring
from app.services.learning.catalog_scope import resolve_catalog_knowledge_key
from app.services.learning.lesson_authoring_feedback import (
    CONSTRAINTS, REPAIRABLE, LessonAuthorFeedback, LessonFeedbackIssue, attempt_diagnostic,
)
from app.services.learning.lesson_contracts import (
    LESSON_COMPLETION_VERSION, LESSON_CONTENT_STANDARD_VERSION, LESSON_GENERATOR_VERSION,
    LESSON_POLICY_VERSION, LessonDocumentDraft, LessonSourceSnapshot,
    calculate_lesson_impact, canonical_source_set_hash, lesson_evidence_identity,
    parse_lesson_document_candidate,
)
from app.services.learning.lesson_quality import LessonQualityError, LessonQualityReport, require_lesson_quality
from app.services.learning.lesson_repository import (
    LessonAuthoringRunRecord, LessonScopeRecord, LessonVersionConflict, PostgresLessonDocumentRepository,
)
from app.services.llm.completion_policy import resolve_completion_stage_policy
from app.services.llm.http_execution import LLMHTTPExecution, LLMHTTPExecutionError, use_http_execution


class LessonLeaseHeartbeat:
    """Only renew liveness, on a separate short connection every forty seconds."""

    def __init__(self, run: LessonAuthoringRunRecord, clock: Callable[[], datetime]) -> None:
        self.run, self.clock = run, clock
        self.stopped, self.lost = Event(), Event()
        self.thread = Thread(target=self._pump, name="lesson-completion-heartbeat", daemon=True)

    def renew(self) -> None:
        try:
            with connect() as conn, conn.transaction():
                conn.execute("SET LOCAL statement_timeout = '5s'")
                conn.execute("SET LOCAL lock_timeout = '2s'")
                if not PostgresLessonDocumentRepository(conn).heartbeat_authoring_run(run=self.run, now=self.clock()):
                    self.lost.set()
        except Exception:
            self.lost.set()

    def _pump(self) -> None:
        while not self.stopped.wait(40):
            self.renew()
            if self.lost.is_set():
                return

    def ensure(self) -> None:
        if self.lost.is_set():
            raise LessonVersionConflict("Lesson completion heartbeat lost")

    def __enter__(self) -> LessonLeaseHeartbeat:
        self.renew()
        self.ensure()
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.stopped.set()
        self.thread.join(timeout=5)


def stage_dependency(
    *, run: LessonAuthoringRunRecord, scope: LessonScopeRecord,
    snapshots: tuple[LessonSourceSnapshot, ...], stage_kind: str,
    policy: Mapping[str, object], standard_dependency_hash: str | None = None,
    standard_document_hash: str | None = None,
    personalization: Mapping[str, object] | None = None,
) -> dict[str, object]:
    # Standard applicability excludes mastery; changing personal conditions does
    # not invalidate a standard with the same goal/curriculum/source dependency.
    result: dict[str, object] = {
        "schema_version": LESSON_COMPLETION_VERSION, "stage_kind": stage_kind,
        "reuse_scope": "same_user_course",
        "user_id": run.user_id, "track_id": run.track_id, "knowledge_key": run.knowledge_key,
        "language_id": scope.language_id, "active_plan_revision_id": scope.active_plan_revision_id,
        "title": scope.node_title, "node_description": scope.node_description,
        "goal_text": scope.goal_text, "target_level": scope.target_level,
        "required_capabilities": list(scope.required_capabilities),
        "generator_version": LESSON_GENERATOR_VERSION, "policy_version": LESSON_POLICY_VERSION,
        "content_standard_version": LESSON_CONTENT_STANDARD_VERSION,
        "stage_policy": dict(policy), "evidence": lesson_evidence_identity(snapshots),
    }
    if stage_kind == "personalized":
        result.update(profile_hash=run.profile_hash, mastery_level=scope.mastery_level,
                      mastery_confidence=scope.mastery_confidence,
                      standard_dependency_hash=standard_dependency_hash,
                      standard_document_hash=standard_document_hash, personalization=dict(personalization or {}))
    return result


def _feedback(value: object) -> LessonAuthorFeedback | None:
    if not value:
        return None
    if not isinstance(value, dict) or value.get("schema_version") != "lesson_author_feedback_v2":
        raise ValueError("Invalid completion feedback")
    issues = value.get("issues")
    if not isinstance(issues, list):
        raise ValueError("Invalid completion issues")
    return LessonAuthorFeedback(
        str(value["document_kind"]), str(value["failed_stage"]), int(str(value["previous_attempt_index"])),
        tuple(LessonFeedbackIssue(str(item["code"]), str(item["location"])) for item in issues),
        schema_version="lesson_author_feedback_v2",
    )


def _check_current(run: LessonAuthoringRunRecord, snapshots: tuple[LessonSourceSnapshot, ...], clock: Callable[[], datetime]) -> None:
    with connect() as conn, conn.transaction():
        repository = PostgresLessonDocumentRepository(conn)
        repository.assert_authoring_current(run=run, now=clock())
        if not repository.evidence_is_current(snapshots):
            raise LessonVersionConflict("Lesson completion evidence is no longer current")


def _validate(
    candidate: Mapping[str, object], request: authoring.LessonAuthoringRequest,
    handles: Mapping[str, str], snapshots: tuple[LessonSourceSnapshot, ...], attempt_index: int,
) -> tuple[LessonDocumentDraft | None, LessonQualityReport | None, LessonAuthorFeedback | None]:
    document: LessonDocumentDraft | None = None
    try:
        document = authoring._parse_author_candidate(candidate, handles)
        authoring._assert_candidate_identity(document, request)
        quality = require_lesson_quality(
            document, snapshots, document_kind="standard" if request.document_kind == "standard" else "personalized",
            standard_document=request.standard_document,
        )
        return document, quality, None
    except LessonQualityError as exc:
        issues = tuple(LessonFeedbackIssue(
            issue.code if issue.code in CONSTRAINTS else "LESSON_AUTHOR_INTERNAL_FAILURE",
            next((f"blocks[{i}]" for i, block in enumerate(document.blocks) if block.block_id == issue.block_id), "document") if document else "document",
        ) for issue in exc.report.issues)
        issues = tuple(issue for issue in issues if issue.code not in REPAIRABLE) + tuple(issue for issue in issues if issue.code in REPAIRABLE)
        return None, exc.report, LessonAuthorFeedback(request.document_kind, "quality_gate", attempt_index, issues[:12], "lesson_author_feedback_v2")
    except authoring.LessonAuthoringFailure as exc:
        return None, None, LessonAuthorFeedback(request.document_kind, exc.stage, attempt_index, exc.issues, "lesson_author_feedback_v2")


def _require_progress(attempts: tuple[dict[str, object], ...], run_id: str) -> LessonAuthorFeedback | None:
    rejected = [row for row in attempts if row["state"] == "rejected"]
    if not rejected:
        return None
    if rejected[-1]["execution_outcome"] == "not_started" and str(rejected[-1]["run_id"]) != run_id:
        # A fresh explicit run may retry a proven-not-started operation, never
        # an expired/unknown execution or an unchanged content repair loop.
        return None
    latest = _feedback(rejected[-1]["feedback_json"])
    if latest is None or not latest.repairable or rejected[-1]["execution_outcome"] != "known":
        raise authoring.LessonAuthoringFailure("LESSON_DOCUMENT_QUALITY_BLOCKED", "课程阶段没有可安全续行的修复结果。", outcome="invalid")
    signature = tuple((issue.code, issue.location) for issue in latest.issues)
    latest_result = cast(dict[str, object], rejected[-1]["result_json"])
    for previous in rejected[:-1]:
        prior = _feedback(previous["feedback_json"])
        prior_result = cast(dict[str, object], previous["result_json"])
        if ((prior is not None and tuple((issue.code, issue.location) for issue in prior.issues) == signature)
                or (latest_result.get("candidate_hash") is not None
                    and latest_result["candidate_hash"] == prior_result.get("candidate_hash"))):
            raise authoring.LessonAuthoringFailure("LESSON_DOCUMENT_QUALITY_BLOCKED", "课程定向修复未产生新进展。", outcome="invalid")
    return latest


def complete_stage(
    *, run: LessonAuthoringRunRecord, request: authoring.LessonAuthoringRequest,
    dependency: Mapping[str, object], snapshots: tuple[LessonSourceSnapshot, ...],
    handles: Mapping[str, str], port: authoring.LessonDocumentAuthorPort,
    clock: Callable[[], datetime], heartbeat: LessonLeaseHeartbeat,
    standard_attempt_id: str | None = None,
) -> tuple[LessonDocumentDraft, LessonQualityReport, dict[str, object]]:
    """Commit intent -> provider -> actual result/feedback -> separate acceptance."""
    if run.completion_contract_version != LESSON_COMPLETION_VERSION or request.completion_contract_version != LESSON_COMPLETION_VERSION:
        raise ValueError("Completion stages require an explicitly opted-in new Lesson run")
    while True:
        heartbeat.ensure()
        _check_current(run, snapshots, clock)
        with connect() as conn:
            attempts = PostgresLessonDocumentRepository(conn).read_completion_attempts(
                run=run, stage_kind=request.document_kind, dependency=dependency,
            )
        if any(row["state"] == "outcome_unknown" for row in attempts):
            raise authoring.LessonAuthoringFailure("LESSON_EXECUTION_OUTCOME_UNKNOWN", "课程阶段执行结果未知，不能自动重放。")
        if any(row["state"] == "intent" for row in attempts):
            raise authoring.LessonAuthoringFailure("LESSON_STAGE_UNCLOSED", "已有课程阶段尚未闭合，不能重复派发。")
        accepted = next((row for row in reversed(attempts) if row["state"] == "accepted"), None)
        if accepted is not None:
            accepted_document = parse_lesson_document_candidate(cast(Mapping[str, object], accepted["document_json"]))
            if accepted_document.content_hash != accepted["document_hash"]:
                raise ValueError("Stored accepted Lesson hash changed")
            # Reuse is exact same-user/course DATA; current source and quality are
            # checked again, not restored from an old passed/current flag.
            authoring._assert_candidate_identity(accepted_document, request)
            accepted_quality = require_lesson_quality(accepted_document, snapshots,
                document_kind="standard" if request.document_kind == "standard" else "personalized",
                standard_document=request.standard_document)
            return accepted_document, accepted_quality, accepted
        saved = next((row for row in reversed(attempts) if row["state"] == "result_saved"), None)
        if saved is not None:
            if str(saved["run_id"]) != run.run_id:
                raise LessonVersionConflict("An earlier run has a committed result awaiting reconciliation")
            result = cast(dict[str, object], saved["result_json"])
            feedback = _feedback(saved["feedback_json"])
            document: LessonDocumentDraft | None = None
            quality: LessonQualityReport | None = None
            if feedback is None:
                document, quality, checked_feedback = _validate(
                    cast(Mapping[str, object], result["candidate"]), request, handles, snapshots,
                    int(str(saved["stage_attempt_index"])),
                )
                if checked_feedback is not None:
                    raise LessonVersionConflict("Saved result no longer satisfies its validation dependency")
            if cast(datetime, saved["result_saved_at"]) > cast(datetime, saved["result_deadline_at"]):
                raise LessonVersionConflict("Late Lesson result retained without acceptance")
            heartbeat.ensure()
            _check_current(run, snapshots, clock)
            with connect() as conn, conn.transaction():
                decided = PostgresLessonDocumentRepository(conn).decide_completion_result(
                    run=run, attempt=saved, document=document,
                    quality=quality.safe_summary() if quality else {"passed": False}, now=clock(),
                )
            if document is not None and quality is not None:
                return document, quality, decided
            continue
        previous_feedback = _require_progress(attempts, run.run_id)
        request = replace(request, previous_attempt_feedback=previous_feedback)
        with connect() as conn, conn.transaction():
            repository = PostgresLessonDocumentRepository(conn)
            if not repository.evidence_is_current(snapshots):
                raise LessonVersionConflict("Lesson evidence changed before intent")
            intent = repository.begin_completion_attempt(
                run=run, stage_kind=request.document_kind, dependency=dependency,
                request_hash=authoring._hash_json(authoring._safe_request_payload(request)),
                standard_attempt_id=standard_attempt_id, now=clock(),
            )
        if intent is None:
            continue
        # The preceding context has COMMITted before any provider call.
        index = int(str(intent["stage_attempt_index"]))
        response: authoring.LessonAuthoringResponse | None = None
        observed_usage = None
        observed_diagnostics = None
        feedback = None
        execution_outcome, usage_status = "known", "unknown"
        result = {}

        def before_send() -> float:
            heartbeat.ensure()
            _check_current(run, snapshots, clock)
            return (cast(datetime, intent["request_deadline_at"]) - clock()).total_seconds()

        # One durable intent per physical dispatch; never inherit hidden legacy
        # transport retries. Further semantic work has its own committed intent.
        execution = LLMHTTPExecution(before_send, heartbeat.ensure, max_attempts=1,
            execution_profile=TutorExecutionProfile.COMPLETION_DRIVEN_V1)
        try:
            with use_http_execution(execution):
                response = port.author(request)
            observed_usage, observed_diagnostics = response.usage, response.response_diagnostics
            # Bounded private candidate DATA, never an export/public receipt.
            import json
            raw = json.dumps(response.candidate, ensure_ascii=False, sort_keys=True, allow_nan=False)
            if len(raw.encode("utf-8")) > 524_288:
                result = {"candidate_omitted": "size_limit", "candidate_bytes": len(raw.encode("utf-8"))}
                failure = authoring.LessonAuthoringFailure("LESSON_DOCUMENT_INVALID", "课程候选超过阶段存储限制。", outcome="invalid")
                failure.execution_outcome = "known"
                raise failure
            result = {"candidate": dict(response.candidate), "candidate_hash": authoring._hash_json(response.candidate)}
            _document, _quality, feedback = _validate(response.candidate, request, handles, snapshots, index)
        except authoring.LessonAuthoringFailure as exc:
            execution_outcome = exc.execution_outcome
            feedback = LessonAuthorFeedback(request.document_kind, exc.stage, index, exc.issues, "lesson_author_feedback_v2")
            result.update(failure_code=exc.code)
            if response is None:
                observed_usage, observed_diagnostics = exc.usage, exc.response_diagnostics
                result.update(provider=exc.provider, model=exc.model, protocol=exc.protocol,
                              usage=asdict(exc.usage) if exc.usage else None)
                usage_status = "known" if authoring._usage_mapping(exc.usage) is not None else "not_started" if execution_outcome == "not_started" else "unknown"
        except LLMHTTPExecutionError as exc:
            observed_usage, observed_diagnostics = exc.usage, exc.response_diagnostics
            execution_outcome = "unknown" if exc.outcome_unknown else "known" if exc.reason == "http_error" else "not_started"
            usage_status = "known" if authoring._usage_mapping(exc.usage) is not None else "not_started" if execution_outcome == "not_started" else "unknown"
            feedback = LessonAuthorFeedback(request.document_kind, "provider_response", index,
                (LessonFeedbackIssue("LESSON_PROVIDER_UNAVAILABLE"),), "lesson_author_feedback_v2")
            result.update(failure_code="LESSON_EXECUTION_OUTCOME_UNKNOWN" if exc.outcome_unknown else "LESSON_DOCUMENT_GENERATION_UNAVAILABLE",
                          usage=asdict(exc.usage) if exc.usage else None)
        except Exception:
            # An exception without a known provider closure is not a retry permit.
            execution_outcome = "known" if response is not None else "unknown"
            feedback = LessonAuthorFeedback(request.document_kind, "provider_response", index,
                (LessonFeedbackIssue("LESSON_AUTHOR_INTERNAL_FAILURE"),), "lesson_author_feedback_v2")
            result.update(failure_code="LESSON_EXECUTION_OUTCOME_UNKNOWN")
        if response is not None:
            result.update(provider=response.provider, model=response.model, protocol=response.protocol,
                          usage=asdict(response.usage) if response.usage else None)
            usage_status = "known" if authoring._usage_mapping(response.usage) is not None else "unknown"
        result["diagnostic"] = attempt_diagnostic(
            request.document_kind, index, feedback,
            response_diagnostics=observed_diagnostics, usage=observed_usage, completion_driven=True,
        )
        result["physical_dispatch_attempts"] = execution.physical_attempts
        with connect() as conn, conn.transaction():
            PostgresLessonDocumentRepository(conn).save_completion_result(
                attempt=intent, result=result, feedback=feedback.payload() if feedback else {},
                execution_outcome=execution_outcome, usage_status=usage_status, now=clock(),
            )
        # Loop back through the durable result, never accepting the in-memory
        # provider object. Failure/unknown writes are equally durable.


def dispatch_completion_lesson(
    *, run: LessonAuthoringRunRecord, author: authoring.LessonDocumentAuthorPort | None,
    clock: Callable[[], datetime],
) -> None:
    settings = get_settings()
    if not settings.tutor_completion_driven_enabled:
        raise authoring.LessonAuthoringFailure("LESSON_COMPLETION_DISABLED", "完成驱动课程生成尚未启用。")
    policy = resolve_completion_stage_policy(settings, "lesson_authoring")
    if policy.timeout_seconds != 600 or policy.max_output_tokens != 12_000:
        raise ValueError("Lesson completion stage requires the approved 600s/12000 policy")
    policy_identity = {**asdict(policy), "provider": settings.llm_provider_type, "model": settings.llm_model}
    with LessonLeaseHeartbeat(run, clock) as heartbeat:
        with connect() as conn:
            repository = PostgresLessonDocumentRepository(conn)
            scope = repository.read_scope(user_id=run.user_id, track_id=run.track_id, knowledge_key=run.knowledge_key)
            personalization = repository.read_personalization_context(scope)
            catalog_key = resolve_catalog_knowledge_key(conn, user_id=scope.user_id, track_id=scope.track_id,
                plan_revision_id=scope.active_plan_revision_id, knowledge_key=scope.knowledge_key)
            topics = tuple(dict.fromkeys((catalog_key, *(key for key in scope.required_capabilities if key != scope.language_id))))
            snapshots = authoring._load_evidence_snapshots(conn, scope.language_id, catalog_key, scope.node_title,
                clock(), completion_driven=True, required_topics=topics)
            current_state = repository.read_lesson_state(user_id=run.user_id, track_id=run.track_id, knowledge_key=run.knowledge_key)
        if not snapshots:
            raise authoring.LessonAuthoringFailure("LESSON_SOURCE_EVIDENCE_INSUFFICIENT", "当前没有足够的受信课程来源。", outcome="invalid")
        source_hash = canonical_source_set_hash(snapshots)
        with connect() as conn, conn.transaction():
            PostgresLessonDocumentRepository(conn).set_authoring_source_set(
                run_id=run.run_id, lease_generation=run.lease_generation, source_set_hash=source_hash)
        evidence, handles = authoring._authoring_evidence(snapshots)
        port = author or authoring.LESSON_AUTHOR_FACTORY()
        standard_request = authoring.LessonAuthoringRequest(
            document_kind="standard", language_id=scope.language_id, knowledge_key=scope.knowledge_key,
            title=scope.node_title, goal_text=scope.goal_text, target_level=scope.target_level,
            required_capabilities=scope.required_capabilities, mastery_level="unseen", mastery_confidence=0.0,
            evidence=evidence, completion_contract_version=LESSON_COMPLETION_VERSION)
        standard_dependency = stage_dependency(run=run, scope=scope, snapshots=snapshots, stage_kind="standard", policy=policy_identity)
        standard, standard_quality, accepted_standard = complete_stage(
            run=run, request=standard_request, dependency=standard_dependency, snapshots=snapshots,
            handles=handles, port=port, clock=clock, heartbeat=heartbeat)
        standard_hash = authoring._hash_json(standard_dependency)
        with connect() as conn:
            prior = PostgresLessonDocumentRepository(conn).read_prior_personalized_stage(run=run, standard_dependency_hash=standard_hash)
        previous = parse_lesson_document_candidate(cast(Mapping[str, object], prior["document_json"])) if prior else None
        if previous is not None and prior is not None and previous.content_hash != prior["document_hash"]:
            raise ValueError("Stored personalized stage hash changed")
        editable = tuple(block.block_id for block in previous.blocks if block.type in {
            "concept", "code_example", "comparison", "hint", "summary", "next_steps",
        }) if previous else ()
        personal_request = replace(standard_request, document_kind="personalized", mastery_level=scope.mastery_level,
            mastery_confidence=scope.mastery_confidence, standard_document=standard, citation_handles=tuple(handles.items()),
            previous_personalized_document=previous, editable_block_ids=editable)
        personal_request = replace(personal_request, personal_preferences=tuple(personalization.items()))
        personal_dependency = stage_dependency(run=run, scope=scope, snapshots=snapshots, stage_kind="personalized",
            policy=policy_identity, standard_dependency_hash=standard_hash, standard_document_hash=standard.content_hash,
            personalization=personalization)
        personal, personal_quality, _accepted_personal = complete_stage(
            run=run, request=personal_request, dependency=personal_dependency, snapshots=snapshots,
            handles=handles, port=port, clock=clock, heartbeat=heartbeat, standard_attempt_id=str(accepted_standard["id"]))
        current_document = current_state.get("document")
        impact = calculate_lesson_impact(current_document if isinstance(current_document, LessonDocumentDraft) else standard, personal,
            current_source_ids=tuple(item.source_id for item in cast(tuple[LessonSourceSnapshot, ...], current_state.get("sources") or ())),
            candidate_source_ids=tuple(item.source_id for item in snapshots))
        heartbeat.ensure()
        with connect() as conn, conn.transaction():
            PostgresLessonDocumentRepository(conn).publish_authoring_result(
                run=run, standard_document=standard, personalized_document=personal, snapshots=snapshots,
                standard_quality=standard_quality.safe_summary(), personalized_quality=personal_quality.safe_summary(),
                standard_change_summary={"kind": "standard", "completion_contract_version": LESSON_COMPLETION_VERSION},
                personalized_change_summary={"kind": "personalized", "goal_bound": True},
                generator_version=LESSON_GENERATOR_VERSION + ".completion1", policy_version=LESSON_POLICY_VERSION,
                source_set_hash=source_hash, impact=impact, now=clock())

"""Deterministic model code-review fixtures for publication and scoring tests."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.learning.practice.contracts import (
    ExercisePrivateRubric,
    ExerciseSourceKind,
    ExerciseType,
    ExerciseVersion,
    canonical_hash,
)
from app.services.learning.practice.model_review_contracts import code_hash
from app.services.learning.practice.model_review_quality import candidate_hash


@dataclass(frozen=True, slots=True)
class ModelReviewFixture:
    exercise: ExerciseVersion
    rubric: ExercisePrivateRubric
    validation_profile_version: str

    @property
    def candidate_hash(self) -> str:
        return candidate_hash(self.exercise, self.rubric)


def _fixture(
    *,
    language: str,
    key: str,
    title: str,
    requirements: tuple[str, ...],
    code: str,
    scenario: str,
    verdict: str,
    findings: tuple[dict[str, object], ...],
    tests: tuple[dict[str, object], ...],
    capability: str,
) -> ModelReviewFixture:
    normalized = code.replace("\r\n", "\n").replace("\r", "\n")
    exercise = ExerciseVersion(
        language_id=language,
        exercise_key=key,
        exercise_type=ExerciseType.MODEL_CODE_REVIEW,
        version="v1",
        source_kind=ExerciseSourceKind.CURATED_FIXTURE,
        title=title,
        learner_prompt={
            "schema_version": "model_code_review_prompt_v1",
            "requirements": list(requirements),
            "review_scope": ["correctness", "regression", "evidence"],
            "evidence_boundary": "prepublication_verified",
            "learner_instruction": "判断代码是否满足需求，并提交结构化审核结论与证据。",
        },
        starter_artifact={
            "schema_version": "model_code_review_artifact_v1",
            "language_id": language,
            "runtime_label": {"python": "Python 3", "javascript": "JavaScript", "typescript": "TypeScript", "sql": "SQLite"}[language],
            "model_code": normalized,
            "code_hash": code_hash(normalized),
            "line_count": len(normalized.splitlines()),
        },
        required_capabilities=(capability,),
        runtime_profile_id=None,
        execution_required=False,
        public_feedback_policy_version="model_code_review_feedback_v1",
    )
    rubric = ExercisePrivateRubric(
        rubric_version="v1",
        private_test_bundle=tests,
        reference_answer={
            "schema_version": "model_code_review_rubric_v1",
            "scenario_kind": scenario,
            "expected_verdict": verdict,
            "expected_findings": list(findings),
            "visible_evidence_ids": ["visible-summary-1"],
            "coverage_policy": "model_review_coverage_v1",
            "score_policy_version": "model_code_review_score_v1",
            "feedback_policy_version": "model_code_review_feedback_v1",
        },
        score_policy={"kind": "model_code_review", "policy_version": "model_code_review_score_v1", "threshold": 0.8},
    )
    return ModelReviewFixture(exercise, rubric, "model_review_validation_v1")


def _finding(key: str, *, kind: str, category: str, severity: str, line: int, tokens: tuple[str, ...]) -> dict[str, object]:
    return {
        "finding_key": key,
        "finding_kind": kind,
        "category": category,
        "severity": severity,
        "accepted_line_ranges": [{"start_line": line, "end_line": line}],
        "matcher_tokens": list(tokens),
        "reachability_proof_ids": [f"proof-{key}"] if kind == "correctness" else [],
        "minimum_token_matches": 1,
    }


MODEL_REVIEW_FIXTURES: tuple[ModelReviewFixture, ...] = (
    _fixture(
        language="python", key="python.review.single-zero", title="审核除零边界",
        requirements=("返回 total / count；count 为 0 时返回 0。",),
        code="def average(total, count):\n    return total / count",
        scenario="single_correctness_issue", verdict="correctness_issue",
        findings=(_finding("zero-division", kind="correctness", category="edge_case", severity="high", line=2, tokens=("count", "zero", "guard", "除零")),),
        tests=({"case_type": "visible", "input": {"total": 6, "count": 2}, "expected": {"value": 3}, "order_index": 0}, {"case_type": "hidden", "input": {"total": 0, "count": 0}, "expected": {"value": 0}, "order_index": 1}),
        capability="python.functions.edge_cases",
    ),
    _fixture(
        language="javascript", key="javascript.review.multiple", title="审核用户标签渲染",
        requirements=("空名称显示 Guest。", "标签文本必须使用传入 name。"),
        code="function label(name) {\n  const shown = name || '';\n  return 'User: ' + 'name';\n}",
        scenario="multiple_correctness_issues", verdict="correctness_issue",
        findings=(
            _finding("empty-fallback", kind="correctness", category="fallback", severity="medium", line=2, tokens=("guest", "empty", "fallback", "空")),
            _finding("literal-name", kind="correctness", category="wrong_value", severity="high", line=3, tokens=("literal", "name", "parameter", "变量")),
        ),
        tests=({"case_type": "visible", "input": {"name": "Ada"}, "expected": {"value": "User: Ada"}, "order_index": 0}, {"case_type": "hidden", "input": {"name": ""}, "expected": {"value": "User: Guest"}, "order_index": 1}),
        capability="javascript.functions.contracts",
    ),
    _fixture(
        language="typescript", key="typescript.review.improvement", title="审核只读查找函数",
        requirements=("返回匹配用户；不存在时返回 undefined。",),
        code="type User = { id: number; name: string };\nfunction findUser(users: User[], id: number): User | undefined {\n  return users.find((user) => user.id === id);\n}",
        scenario="improvement_only", verdict="improvement_only",
        findings=(_finding("readonly-input", kind="improvement", category="maintainability", severity="low", line=2, tokens=("readonly", "input", "mutation", "只读")),),
        tests=({"case_type": "visible", "input": {"id": 1}, "expected": {"name": "Ada"}, "order_index": 0}, {"case_type": "hidden", "input": {"id": 9}, "expected": {"value": None}, "order_index": 1}),
        capability="typescript.functions.types",
    ),
    _fixture(
        language="sql", key="sql.review.correct", title="审核启用用户查询",
        requirements=("只返回 active = 1 的用户名称，并按名称升序。",),
        code="SELECT name\nFROM users\nWHERE active = 1\nORDER BY name ASC;",
        scenario="fully_correct", verdict="no_correctness_issue", findings=(),
        tests=({"case_type": "visible", "input": {}, "expected": {"rows": ["Ada"]}, "order_index": 0}, {"case_type": "hidden", "input": {}, "expected": {"ordered": True}, "order_index": 1}),
        capability="sql.select.where",
    ),
    _fixture(
        language="python", key="python.review.suspicious-correct", title="审核短路条件",
        requirements=("仅在 value 非空且为正数时返回 True。",),
        code="def is_positive(value):\n    return bool(value and value > 0)",
        scenario="suspicious_but_correct", verdict="no_correctness_issue", findings=(),
        tests=({"case_type": "visible", "input": {"value": 2}, "expected": {"value": True}, "order_index": 0}, {"case_type": "hidden", "input": {"value": None}, "expected": {"value": False}, "order_index": 1}),
        capability="python.booleans.short_circuit",
    ),
    _fixture(
        language="typescript", key="typescript.review.regression", title="审核边界修复回归",
        requirements=("索引越界返回 undefined。", "索引 0 必须返回第一项。"),
        code="function at<T>(items: T[], index: number): T | undefined {\n  if (index <= 0 || index >= items.length) return undefined;\n  return items[index];\n}",
        scenario="fix_introduces_regression", verdict="correctness_issue",
        findings=(_finding("zero-index-regression", kind="correctness", category="boundary", severity="high", line=2, tokens=("index", "zero", "first", "边界")),),
        tests=({"case_type": "visible", "input": {"index": 9}, "expected": {"value": None}, "order_index": 0}, {"case_type": "hidden", "input": {"index": 0}, "expected": {"value": "first"}, "order_index": 1}),
        capability="typescript.arrays.boundaries",
    ),
)


def model_review_fixture_for_language(language_id: str) -> ModelReviewFixture | None:
    normalized = language_id.strip().lower()
    return next((fixture for fixture in MODEL_REVIEW_FIXTURES if fixture.exercise.language_id == normalized), None)


def validation_checks_for_fixture(fixture: ModelReviewFixture) -> tuple[dict[str, object], ...]:
    kinds = (
        "schema", "parser", "compile_or_typecheck", "visible_tests", "hidden_tests",
        "finding_reachability", "rubric_consistency", "coverage", "redaction",
    )
    return tuple(
        {"check_type": kind, "status": "passed", "proof_hash": canonical_hash({"candidate": fixture.candidate_hash, "check": kind})}
        for kind in kinds
    )

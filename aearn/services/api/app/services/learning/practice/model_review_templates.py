"""Developer-owned templates for model code-review authoring.

The primary model may author only learner-facing scenario copy and candidate
code. Tests, expected findings, coverage proofs, score policy, and validation
rubric are rebuilt here from a versioned server-owned template.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.teaching_safety import check_teaching_output
from app.services.learning.practice.contracts import (
    ExercisePrivateRubric,
    ExerciseSourceKind,
    ExerciseType,
    ExerciseVersion,
    canonical_hash,
)
from app.services.learning.practice.model_review_contracts import (
    ModelReviewArtifactV1,
    ModelReviewExpectedFindingV1,
    ModelReviewFindingKind,
    ModelReviewPromptV1,
    ModelReviewRubricV1,
    ModelReviewScenarioKind,
    ModelReviewSeverity,
    ModelReviewVerdict,
    code_hash,
)


MODEL_REVIEW_AUTHOR_CANDIDATE_SCHEMA_VERSION = "model_review_author_candidate_v2"
MODEL_REVIEW_AUTHOR_CANDIDATE_SCHEMA_NAME = "model_review_author_candidate_v2"
MODEL_REVIEW_TEMPLATE_POLICY_VERSION = "model_review_template_policy_v1"

_RUNTIME_LABELS = {
    "python": "Python 3",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "sql": "SQLite",
}
_LANGUAGE_FORBIDDEN_FRAGMENTS = {
    "python": (
        "import ", "from ", "open(", "exec(", "eval(", "compile(", "__", "os.", "sys.", "subprocess",
        "socket", "pathlib", "requests", "urllib",
    ),
    "javascript": (
        "import ", "require(", "fetch(", "xmlhttprequest", "process.", "eval(", "new function", "child_process",
        "fs.", "deno.", "bun.",
    ),
    "typescript": (
        "import ", "require(", "fetch(", "xmlhttprequest", "process.", "eval(", "new function", "child_process",
        "fs.", "deno.", "bun.",
    ),
    "sql": (
        "pragma ", "attach ", "detach ", "insert ", "update ", "delete ", "drop ", "create ", "alter ",
        "replace ", "vacuum ", "load_extension", "--", "/*", "*/",
    ),
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ModelReviewAuthorCandidateV2(_StrictModel):
    """The complete and only model-authored payload for Model Review."""

    schema_version: Literal["model_review_author_candidate_v2"]
    title: str = Field(min_length=1, max_length=160)
    learner_instruction: str = Field(min_length=1, max_length=1_200)
    candidate_code: str = Field(min_length=1, max_length=48_000)

    @field_validator("title", "learner_instruction")
    @classmethod
    def _validate_teaching_copy(cls, value: str) -> str:
        if check_teaching_output(value).blocked:
            raise ValueError("model review author copy failed teaching safety")
        return value


class ModelReviewControlledTestCaseV1(_StrictModel):
    """Private server-owned test DSL; never part of the model output schema."""

    id: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    case_type: Literal["visible", "hidden"]
    input: dict[str, object]
    expected: dict[str, object]
    assertion: str = Field(max_length=4_000)
    timeout_ms: int = Field(ge=1, le=10_000)
    order_index: int = Field(ge=0, le=64)
    candidate_expected_pass: bool
    proof_ids: tuple[str, ...] = Field(default=(), max_length=16)

    @field_validator("proof_ids")
    @classmethod
    def _validate_proof_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or any(
            not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,159}", value) for value in values
        ):
            raise ValueError("model review proof ids must be unique stable identifiers")
        return values


def model_review_author_output_schema() -> dict[str, object]:
    return ModelReviewAuthorCandidateV2.model_json_schema()


@dataclass(frozen=True, slots=True)
class ModelReviewFindingTemplate:
    finding_key: str
    finding_kind: ModelReviewFindingKind
    category: str
    severity: ModelReviewSeverity
    line_anchor_fragments: tuple[str, ...]
    matcher_tokens: tuple[str, ...]
    reachability_proof_ids: tuple[str, ...] = ()
    minimum_token_matches: int = 1

    def build(self, code: str) -> dict[str, object]:
        line = _locate_line(code, self.line_anchor_fragments)
        return {
            "finding_key": self.finding_key,
            "finding_kind": self.finding_kind.value,
            "category": self.category,
            "severity": self.severity.value,
            "accepted_line_ranges": [{"start_line": line, "end_line": line}],
            "matcher_tokens": list(self.matcher_tokens),
            "reachability_proof_ids": list(self.reachability_proof_ids),
            "minimum_token_matches": self.minimum_token_matches,
        }


@dataclass(frozen=True, slots=True)
class ModelReviewTemplate:
    template_id: str
    version: str
    language_id: str
    capability_hint: str
    requirements: tuple[str, ...]
    review_scope: tuple[str, ...]
    scenario_kind: ModelReviewScenarioKind
    expected_verdict: ModelReviewVerdict
    candidate_intent: str
    required_code_fragments: tuple[str, ...]
    forbidden_code_fragments: tuple[str, ...]
    finding_templates: tuple[ModelReviewFindingTemplate, ...]
    test_bundle: tuple[ModelReviewControlledTestCaseV1, ...]
    example_title: str
    example_instruction: str
    example_code: str
    max_code_lines: int = 80

    @property
    def contract_hash(self) -> str:
        return canonical_hash(
            {
                "policy_version": MODEL_REVIEW_TEMPLATE_POLICY_VERSION,
                "template_id": self.template_id,
                "version": self.version,
                "language_id": self.language_id,
                "capability_hint": self.capability_hint,
                "requirements": self.requirements,
                "review_scope": self.review_scope,
                "scenario_kind": self.scenario_kind.value,
                "expected_verdict": self.expected_verdict.value,
                "candidate_intent": self.candidate_intent,
                "required_code_fragments": self.required_code_fragments,
                "forbidden_code_fragments": self.forbidden_code_fragments,
                "finding_templates": [
                    {
                        "finding_key": item.finding_key,
                        "finding_kind": item.finding_kind.value,
                        "category": item.category,
                        "severity": item.severity.value,
                        "line_anchor_fragments": item.line_anchor_fragments,
                        "matcher_tokens": item.matcher_tokens,
                        "reachability_proof_ids": item.reachability_proof_ids,
                        "minimum_token_matches": item.minimum_token_matches,
                    }
                    for item in self.finding_templates
                ],
                "test_bundle": [item.model_dump(mode="json") for item in self.test_bundle],
                "max_code_lines": self.max_code_lines,
            }
        )

    def public_authoring_spec(self) -> dict[str, object]:
        """Return only what the model needs; no tests, rubric, or proof tokens."""

        return {
            "template_id": self.template_id,
            "template_version": self.version,
            "language_id": self.language_id,
            "requirements": list(self.requirements),
            "review_scope": list(self.review_scope),
            "candidate_intent": self.candidate_intent,
            "required_code_fragments": list(self.required_code_fragments),
            "forbidden_code_fragments": list(self.forbidden_code_fragments),
            "max_code_lines": self.max_code_lines,
        }

    def canonical_author_example(self) -> dict[str, object]:
        return {
            "schema_version": MODEL_REVIEW_AUTHOR_CANDIDATE_SCHEMA_VERSION,
            "title": self.example_title,
            "learner_instruction": self.example_instruction,
            "candidate_code": self.example_code,
        }

    def validate_candidate_code(self, code: str) -> str:
        normalized = code.replace("\r\n", "\n").replace("\r", "\n").strip()
        lines = normalized.splitlines()
        if not normalized or len(lines) > self.max_code_lines:
            raise ValueError("model review candidate code is empty or oversized")
        compact = normalized.casefold()
        if any(fragment.casefold() not in compact for fragment in self.required_code_fragments):
            raise ValueError("model review candidate misses a controlled template fragment")
        forbidden = (*_LANGUAGE_FORBIDDEN_FRAGMENTS[self.language_id], *self.forbidden_code_fragments)
        if any(fragment.casefold() in compact for fragment in forbidden):
            raise ValueError("model review candidate crosses the controlled code boundary")
        if self.language_id == "sql":
            if normalized.count(";") > 1 or not re.match(r"(?is)^\s*select\b", normalized):
                raise ValueError("model review SQL candidate must be one SELECT statement")
        for finding in self.finding_templates:
            _locate_line(normalized, finding.line_anchor_fragments)
        return normalized

    def build_exercise(
        self,
        *,
        author: ModelReviewAuthorCandidateV2,
        knowledge_key: str,
        required_capabilities: tuple[str, ...],
    ) -> tuple[ExerciseVersion, ExercisePrivateRubric]:
        code = self.validate_candidate_code(author.candidate_code)
        prompt = ModelReviewPromptV1(
            requirements=self.requirements,
            review_scope=self.review_scope,
            learner_instruction=author.learner_instruction,
        )
        artifact = ModelReviewArtifactV1(
            language_id=self.language_id,
            runtime_label=_RUNTIME_LABELS[self.language_id],
            model_code=code,
            code_hash=code_hash(code),
            line_count=len(code.splitlines()),
        )
        rubric_contract = ModelReviewRubricV1(
            scenario_kind=self.scenario_kind,
            expected_verdict=self.expected_verdict,
            expected_findings=tuple(ModelReviewExpectedFindingV1.model_validate(item.build(code)) for item in self.finding_templates),
            visible_evidence_ids=("visible-summary-1",),
            coverage_policy="model_review_controlled_template_coverage_v1",
            template_id=self.template_id,
            template_version=self.version,
            template_contract_hash=self.contract_hash,
        )
        seed = canonical_hash(
            {
                "template_id": self.template_id,
                "template_version": self.version,
                "title": author.title,
                "learner_instruction": author.learner_instruction,
                "candidate_code": code,
                "knowledge_key": knowledge_key,
            }
        )
        exercise = ExerciseVersion(
            language_id=self.language_id,
            exercise_key=f"{self.language_id}.review.{knowledge_key}.{seed[:12]}",
            exercise_type=ExerciseType.MODEL_CODE_REVIEW,
            version=f"v2-{seed[:12]}",
            source_kind=ExerciseSourceKind.REGISTERED_AUTHOR,
            title=author.title,
            learner_prompt=prompt.model_dump(mode="json"),
            starter_artifact=artifact.model_dump(mode="json"),
            required_capabilities=required_capabilities,
            runtime_profile_id=None,
            execution_required=False,
            public_feedback_policy_version="model_code_review_feedback_v1",
        )
        private = ExercisePrivateRubric(
            rubric_version="v2",
            private_test_bundle=tuple(item.model_dump(mode="json") for item in self.test_bundle),
            reference_answer=rubric_contract.model_dump(mode="json"),
            score_policy={
                "kind": "model_code_review",
                "policy_version": "model_code_review_score_v1",
                "threshold": 0.8,
            },
        )
        return exercise, private

    def validate_built_candidate(
        self,
        *,
        exercise: ExerciseVersion,
        rubric: ExercisePrivateRubric,
    ) -> None:
        if exercise.language_id != self.language_id:
            raise ValueError("model review template language mismatch")
        prompt = ModelReviewPromptV1.model_validate(dict(exercise.learner_prompt))
        artifact = ModelReviewArtifactV1.model_validate(dict(exercise.starter_artifact))
        private = ModelReviewRubricV1.model_validate(dict(rubric.reference_answer))
        code = self.validate_candidate_code(artifact.model_code)
        if (
            prompt.requirements != self.requirements
            or prompt.review_scope != self.review_scope
            or private.template_id != self.template_id
            or private.template_version != self.version
            or private.template_contract_hash != self.contract_hash
            or private.scenario_kind is not self.scenario_kind
            or private.expected_verdict is not self.expected_verdict
            or private.expected_findings != ModelReviewRubricV1(
                scenario_kind=self.scenario_kind,
                expected_verdict=self.expected_verdict,
                expected_findings=tuple(ModelReviewExpectedFindingV1.model_validate(item.build(code)) for item in self.finding_templates),
                visible_evidence_ids=("visible-summary-1",),
                coverage_policy="model_review_controlled_template_coverage_v1",
                template_id=self.template_id,
                template_version=self.version,
                template_contract_hash=self.contract_hash,
            ).expected_findings
            or canonical_hash([dict(item) for item in rubric.private_test_bundle])
            != canonical_hash([item.model_dump(mode="json") for item in self.test_bundle])
            or str(rubric.score_policy.get("kind")) != "model_code_review"
            or str(rubric.score_policy.get("policy_version")) != "model_code_review_score_v1"
            or _as_float(rubric.score_policy.get("threshold")) != 0.8
        ):
            raise ValueError("model review private material is not template-owned")


def select_model_review_template(
    *,
    language_id: str,
    knowledge_key: str,
    required_capabilities: tuple[str, ...] = (),
    mastery_level: str = "unseen",
) -> ModelReviewTemplate:
    language = language_id.strip().lower()
    candidates = tuple(item for item in MODEL_REVIEW_TEMPLATES if item.language_id == language)
    if not candidates:
        raise ValueError("model review language has no controlled template")
    exact = tuple(item for item in candidates if item.capability_hint in required_capabilities)
    pool = exact or candidates
    seed = "|".join((language, knowledge_key, mastery_level, *sorted(required_capabilities)))
    index = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % len(pool)
    return pool[index]


def model_review_template(template_id: str) -> ModelReviewTemplate:
    try:
        return _TEMPLATES_BY_ID[template_id]
    except KeyError as exc:
        raise ValueError("model review template is not registered") from exc


def validate_controlled_model_review_candidate(
    *,
    exercise: ExerciseVersion,
    rubric: ExercisePrivateRubric,
) -> ModelReviewTemplate:
    private = ModelReviewRubricV1.model_validate(dict(rubric.reference_answer))
    if private.template_id is None:
        raise ValueError("model review candidate has no controlled template identity")
    template = model_review_template(private.template_id)
    template.validate_built_candidate(exercise=exercise, rubric=rubric)
    return template


def model_review_template_coverage_proof(
    *,
    template: ModelReviewTemplate,
    rubric: ExercisePrivateRubric,
) -> dict[str, object]:
    private = ModelReviewRubricV1.model_validate(dict(rubric.reference_answer))
    tests = tuple(dict(item) for item in rubric.private_test_bundle)
    if not tests or not any(str(item.get("case_type")) == "visible" for item in tests):
        raise ValueError("controlled model review needs visible tests")
    if not any(str(item.get("case_type")) == "hidden" for item in tests):
        raise ValueError("controlled model review needs hidden tests")
    orders = tuple(_as_int(item.get("order_index"), default=-1) for item in tests)
    if orders != tuple(range(len(tests))):
        raise ValueError("controlled model review tests must have continuous order")
    expected_outcomes = tuple(bool(item.get("candidate_expected_pass")) for item in tests)
    proof_ids = {
        proof_id
        for item in tests
        for proof_id in _string_sequence(item.get("proof_ids"))
    }
    expected_proofs = {
        proof_id
        for finding in private.expected_findings
        for proof_id in finding.reachability_proof_ids
    }
    if not expected_proofs.issubset(proof_ids):
        raise ValueError("controlled model review tests do not cover each finding proof")
    if template.scenario_kind in {
        ModelReviewScenarioKind.SINGLE_CORRECTNESS_ISSUE,
        ModelReviewScenarioKind.MULTIPLE_CORRECTNESS_ISSUES,
        ModelReviewScenarioKind.FIX_INTRODUCES_REGRESSION,
    } and all(expected_outcomes):
        raise ValueError("error scenario must contain an expected candidate failure")
    if template.scenario_kind in {
        ModelReviewScenarioKind.FULLY_CORRECT,
        ModelReviewScenarioKind.SUSPICIOUS_BUT_CORRECT,
        ModelReviewScenarioKind.IMPROVEMENT_ONLY,
    } and not all(expected_outcomes):
        raise ValueError("correct or improvement scenario must pass all behavior tests")
    return {
        "template_id": template.template_id,
        "template_contract_hash": template.contract_hash,
        "test_count": len(tests),
        "visible_count": sum(str(item.get("case_type")) == "visible" for item in tests),
        "hidden_count": sum(str(item.get("case_type")) == "hidden" for item in tests),
        "expected_outcomes": expected_outcomes,
        "covered_proof_ids": tuple(sorted(proof_ids)),
    }


def expected_model_review_test_outcomes(rubric: ExercisePrivateRubric) -> tuple[tuple[bool, bool], ...]:
    """Return `(visible, expected_pass)` in deterministic executor order."""

    tests = sorted(
        (dict(item) for item in rubric.private_test_bundle),
        key=lambda item: _as_int(item.get("order_index"), default=-1),
    )
    return tuple(
        (str(item.get("case_type")) != "hidden", bool(item.get("candidate_expected_pass")))
        for item in tests
    )


def _as_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _test(
    case_id: str,
    *,
    case_type: Literal["visible", "hidden"],
    input_value: Mapping[str, object],
    expected: Mapping[str, object],
    order_index: int,
    candidate_expected_pass: bool,
    proof_ids: tuple[str, ...] = (),
) -> ModelReviewControlledTestCaseV1:
    return ModelReviewControlledTestCaseV1(
        id=case_id,
        case_type=case_type,
        input=dict(input_value),
        expected=dict(expected),
        assertion="",
        timeout_ms=2_000,
        order_index=order_index,
        candidate_expected_pass=candidate_expected_pass,
        proof_ids=proof_ids,
    )


def _locate_line(code: str, fragments: tuple[str, ...]) -> int:
    lowered = tuple(fragment.casefold() for fragment in fragments)
    for index, line in enumerate(code.splitlines(), start=1):
        compact = line.casefold()
        if all(fragment in compact for fragment in lowered):
            return index
    raise ValueError("model review finding anchor is absent from candidate code")


MODEL_REVIEW_TEMPLATES: tuple[ModelReviewTemplate, ...] = (
    ModelReviewTemplate(
        template_id="model_review.python.average_zero.v1",
        version="v1",
        language_id="python",
        capability_hint="python.functions.edge_cases",
        requirements=("返回 total / count；count 为 0 时返回 0。",),
        review_scope=("correctness", "edge_case", "evidence"),
        scenario_kind=ModelReviewScenarioKind.SINGLE_CORRECTNESS_ISSUE,
        expected_verdict=ModelReviewVerdict.CORRECTNESS_ISSUE,
        candidate_intent="生成一个普通输入可工作、但遗漏 count 为 0 防护的短函数。不要修复该缺陷。",
        required_code_fragments=("def average(", "/ count"),
        forbidden_code_fragments=("count == 0", "count is 0", "if not count", "return 0 if"),
        finding_templates=(
            ModelReviewFindingTemplate(
                finding_key="zero-division",
                finding_kind=ModelReviewFindingKind.CORRECTNESS,
                category="edge_case",
                severity=ModelReviewSeverity.HIGH,
                line_anchor_fragments=("/", "count"),
                matcher_tokens=("count", "zero", "guard", "除零"),
                reachability_proof_ids=("proof-zero-division",),
            ),
        ),
        test_bundle=(
            _test("average-normal", case_type="visible", input_value={"total": 6, "count": 2}, expected={"value": 3}, order_index=0, candidate_expected_pass=True),
            _test("average-zero", case_type="hidden", input_value={"total": 0, "count": 0}, expected={"value": 0}, order_index=1, candidate_expected_pass=False, proof_ids=("proof-zero-division",)),
        ),
        example_title="审核平均值边界",
        example_instruction="根据需求审核这段候选代码，判断是否存在可触发的正确性问题，并给出行号和验证方法。",
        example_code="def average(total, count):\n    return total / count",
    ),
    ModelReviewTemplate(
        template_id="model_review.javascript.user_label.v1",
        version="v1",
        language_id="javascript",
        capability_hint="javascript.functions.contracts",
        requirements=("空名称显示 Guest。", "标签文本必须使用传入 name。"),
        review_scope=("correctness", "fallback", "evidence"),
        scenario_kind=ModelReviewScenarioKind.MULTIPLE_CORRECTNESS_ISSUES,
        expected_verdict=ModelReviewVerdict.CORRECTNESS_ISSUE,
        candidate_intent="生成一个包含两个独立缺陷的短函数：空名称没有 Guest 回退，并且返回文本错误使用字面量 name。",
        required_code_fragments=("function label(", "name || ''", "+ 'name'"),
        forbidden_code_fragments=("guest", "+ name", "${name}"),
        finding_templates=(
            ModelReviewFindingTemplate(
                finding_key="empty-fallback",
                finding_kind=ModelReviewFindingKind.CORRECTNESS,
                category="fallback",
                severity=ModelReviewSeverity.MEDIUM,
                line_anchor_fragments=("name", "||", "''"),
                matcher_tokens=("guest", "empty", "fallback", "空"),
                reachability_proof_ids=("proof-empty-fallback",),
            ),
            ModelReviewFindingTemplate(
                finding_key="literal-name",
                finding_kind=ModelReviewFindingKind.CORRECTNESS,
                category="wrong_value",
                severity=ModelReviewSeverity.HIGH,
                line_anchor_fragments=("+", "'name'"),
                matcher_tokens=("literal", "name", "parameter", "变量"),
                reachability_proof_ids=("proof-literal-name",),
            ),
        ),
        test_bundle=(
            _test("label-name", case_type="visible", input_value={"name": "Ada"}, expected={"value": "User: Ada"}, order_index=0, candidate_expected_pass=False, proof_ids=("proof-literal-name",)),
            _test("label-empty", case_type="hidden", input_value={"name": ""}, expected={"value": "User: Guest"}, order_index=1, candidate_expected_pass=False, proof_ids=("proof-empty-fallback",)),
        ),
        example_title="审核用户标签",
        example_instruction="审核候选函数是否满足名称回退和文本拼接需求，分别记录每个可触发问题。",
        example_code="function label(name) {\n  const shown = name || '';\n  return 'User: ' + 'name';\n}",
    ),
    ModelReviewTemplate(
        template_id="model_review.typescript.readonly_lookup.v1",
        version="v1",
        language_id="typescript",
        capability_hint="typescript.functions.types",
        requirements=("返回匹配用户；不存在时返回 undefined。",),
        review_scope=("correctness", "maintainability", "evidence"),
        scenario_kind=ModelReviewScenarioKind.IMPROVEMENT_ONLY,
        expected_verdict=ModelReviewVerdict.IMPROVEMENT_ONLY,
        candidate_intent="生成行为正确但参数类型仍可收紧为只读数组的短查找函数；不要使用 readonly 或 ReadonlyArray。",
        required_code_fragments=("type user", "function finduser(", ".find("),
        forbidden_code_fragments=("readonly", "readonlyarray"),
        finding_templates=(
            ModelReviewFindingTemplate(
                finding_key="readonly-input",
                finding_kind=ModelReviewFindingKind.IMPROVEMENT,
                category="maintainability",
                severity=ModelReviewSeverity.LOW,
                line_anchor_fragments=("function finduser", "users"),
                matcher_tokens=("readonly", "input", "mutation", "只读"),
            ),
        ),
        test_bundle=(
            _test("find-existing", case_type="visible", input_value={"id": 1}, expected={"name": "Ada"}, order_index=0, candidate_expected_pass=True),
            _test("find-missing", case_type="hidden", input_value={"id": 9}, expected={"value": None}, order_index=1, candidate_expected_pass=True),
        ),
        example_title="审核只读查找函数",
        example_instruction="判断代码是否满足行为需求；如果没有正确性问题，再指出有证据支持的类型设计改进。",
        example_code="type User = { id: number; name: string };\nfunction findUser(users: User[], id: number): User | undefined {\n  return users.find((user) => user.id === id);\n}",
    ),
    ModelReviewTemplate(
        template_id="model_review.sql.active_users.v1",
        version="v1",
        language_id="sql",
        capability_hint="sql.select.where",
        requirements=("只返回 active = 1 的用户名称，并按名称升序。",),
        review_scope=("correctness", "ordering", "evidence"),
        scenario_kind=ModelReviewScenarioKind.FULLY_CORRECT,
        expected_verdict=ModelReviewVerdict.NO_CORRECTNESS_ISSUE,
        candidate_intent="生成一条完全满足筛选和排序需求的 SQLite SELECT 查询，不添加多余语句。",
        required_code_fragments=("select name", "from users", "where active = 1", "order by name asc"),
        forbidden_code_fragments=(),
        finding_templates=(),
        test_bundle=(
            _test("active-users", case_type="visible", input_value={}, expected={"rows": ["Ada"]}, order_index=0, candidate_expected_pass=True),
            _test("active-users-order", case_type="hidden", input_value={}, expected={"ordered": True}, order_index=1, candidate_expected_pass=True),
        ),
        example_title="审核启用用户查询",
        example_instruction="依据筛选和排序需求审核这条查询；没有正确性问题时应明确给出无问题结论。",
        example_code="SELECT name\nFROM users\nWHERE active = 1\nORDER BY name ASC;",
    ),
    ModelReviewTemplate(
        template_id="model_review.python.short_circuit.v1",
        version="v1",
        language_id="python",
        capability_hint="python.booleans.short_circuit",
        requirements=("仅在 value 非空且为正数时返回 True。",),
        review_scope=("correctness", "short_circuit", "evidence"),
        scenario_kind=ModelReviewScenarioKind.SUSPICIOUS_BUT_CORRECT,
        expected_verdict=ModelReviewVerdict.NO_CORRECTNESS_ISSUE,
        candidate_intent="生成一段看起来紧凑但依赖安全短路求值、并完全满足需求的 Python 函数。",
        required_code_fragments=("def is_positive(", "bool(", "and", "> 0"),
        forbidden_code_fragments=(),
        finding_templates=(),
        test_bundle=(
            _test("positive-value", case_type="visible", input_value={"value": 2}, expected={"value": True}, order_index=0, candidate_expected_pass=True),
            _test("none-value", case_type="hidden", input_value={"value": None}, expected={"value": False}, order_index=1, candidate_expected_pass=True),
        ),
        example_title="审核短路条件",
        example_instruction="审核紧凑条件是否真的违反需求；不要因为写法可疑就制造不存在的正确性问题。",
        example_code="def is_positive(value):\n    return bool(value and value > 0)",
    ),
    ModelReviewTemplate(
        template_id="model_review.typescript.index_regression.v1",
        version="v1",
        language_id="typescript",
        capability_hint="typescript.arrays.boundaries",
        requirements=("索引越界返回 undefined。", "索引 0 必须返回第一项。"),
        review_scope=("correctness", "regression", "evidence"),
        scenario_kind=ModelReviewScenarioKind.FIX_INTRODUCES_REGRESSION,
        expected_verdict=ModelReviewVerdict.CORRECTNESS_ISSUE,
        candidate_intent="生成一个试图修复越界问题、但错误把索引 0 也判定为越界的短函数。不要修复该回归。",
        required_code_fragments=("function at<", "index <= 0", "items[index]"),
        forbidden_code_fragments=("index < 0",),
        finding_templates=(
            ModelReviewFindingTemplate(
                finding_key="zero-index-regression",
                finding_kind=ModelReviewFindingKind.CORRECTNESS,
                category="boundary",
                severity=ModelReviewSeverity.HIGH,
                line_anchor_fragments=("index <= 0",),
                matcher_tokens=("index", "zero", "first", "边界"),
                reachability_proof_ids=("proof-zero-index-regression",),
            ),
        ),
        test_bundle=(
            _test("out-of-range", case_type="visible", input_value={"index": 9}, expected={"value": None}, order_index=0, candidate_expected_pass=True),
            _test("zero-index", case_type="hidden", input_value={"index": 0}, expected={"value": "first"}, order_index=1, candidate_expected_pass=False, proof_ids=("proof-zero-index-regression",)),
        ),
        example_title="审核边界修复回归",
        example_instruction="检查越界修复是否破坏了合法边界输入，并用具体行号和可执行验证方法说明。",
        example_code="function at<T>(items: T[], index: number): T | undefined {\n  if (index <= 0 || index >= items.length) return undefined;\n  return items[index];\n}",
    ),
)

_TEMPLATES_BY_ID = {item.template_id: item for item in MODEL_REVIEW_TEMPLATES}
if len(_TEMPLATES_BY_ID) != len(MODEL_REVIEW_TEMPLATES):  # pragma: no cover - import-time developer invariant.
    raise RuntimeError("model review template ids must be unique")
for _registered_template in MODEL_REVIEW_TEMPLATES:  # pragma: no branch - developer-owned registry audit.
    _registered_author = ModelReviewAuthorCandidateV2.model_validate(
        _registered_template.canonical_author_example()
    )
    _registered_exercise, _registered_rubric = _registered_template.build_exercise(
        author=_registered_author,
        knowledge_key="registry.contract",
        required_capabilities=(_registered_template.capability_hint,),
    )
    _registered_template.validate_built_candidate(
        exercise=_registered_exercise,
        rubric=_registered_rubric,
    )
    model_review_template_coverage_proof(
        template=_registered_template,
        rubric=_registered_rubric,
    )


def author_prompt_contract(template: ModelReviewTemplate) -> str:
    """Canonical prompt fragment with exact schema and one valid example."""

    return (
        "Return exactly one JSON object matching this generated JSON Schema: "
        + json.dumps(model_review_author_output_schema(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + ". The only allowed model-authored fields are schema_version, title, learner_instruction, and candidate_code. "
        "The selected template identity is server-owned and must not appear in the response. Do not emit requirements, "
        "tests, hidden tests, expected outcomes, rubric, findings, matcher tokens, proof ids, score policy, validation "
        "rules, commands, paths, provider metadata, or extra keys. A valid example for this selected template is: "
        + json.dumps(template.canonical_author_example(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )

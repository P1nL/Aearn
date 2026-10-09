"""Closed, server-authored PUBLIC task specifications, never items or proof.

Only public projections of registered examples are reused. No fixture authority,
private reference, expected result, hidden case, import, or execution is returned.
Seeds select instances/presentation, NOT independent families. Policies and real
runtime/scorer identities are explicit caller inputs, never guessed here.
"""
from __future__ import annotations

import json
import re
from typing import Literal, cast
from uuid import UUID

from pydantic import Field, model_validator

from app.services.grounding.public_course_contracts import PublicCourseEvidenceBindingV1, validate_public_course_request
from app.services.learning.item_bank.contracts import (
    LearningItemBlueprintV1, LearningItemCodeContentV1, LearningItemDifficultyProfileV1,
    LearningItemInteraction, LearningItemKind, LearningItemPublicationPolicyV1, LearningItemPublicContentV1, LearningItemPublicV1,
    LearningItemPurpose, LearningItemSourceReferenceV1, LearningItemSourceV1, canonical_hash,
)
from app.services.learning.item_supply.contracts import CoverageBlueprintV1, ObjectiveClauseV1, SupplyScopeV1
from app.services.learning.item_supply.evidence import require_exact_material
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_task_families import families_for_course, initial_slot_allocations
from app.services.learning.item_supply.finite_targets.contracts import FiniteSlotAllocationV1, FiniteClauseReferenceV1, Slot, TargetId
from app.services.learning.item_supply.finite_targets.python_kc import KcTaskKind, python_kc_public_content
from app.services.learning.item_supply.finite_targets.python_state import PythonStateTarget, parse_python_state_target
from app.services.learning.item_supply.finite_targets.sqlite_predicates import (
    SqlitePredicateTargetV1, parse_sqlite_target, sqlite_public_task,
)
from app.services.learning.item_supply.generation_contracts import GenerationLimitsV2, GenerationRequestV2, PublicMaterialV2
from app.services.learning.item_supply.matrix import build_support_matrix
from app.services.learning.item_supply.parameter_profiles import FrozenProfileSnapshot
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model

FACTORY_VERSION = "finite-public-spec-v1"
# Explicit Python-only revision; legacy defaults and the spec DTO stay unchanged.
PYTHON_FACTORY_VERSION_V2 = "finite-public-spec-v2"
FLEXIBLE_FACTORY_VERSION = "finite-public-spec-v3"
_CORE_START = "### finite-public-task-v3:start"
_CORE_END = "### finite-public-task-v3:end"
_SLOT_ROLES = {"practice-1": "practice", "practice-2": "practice", "assessment-1": "assessment",
               "assessment-2": "assessment", "guided-remediation": "remediation"}


class FiniteSlotAllocationV2(StorageContract):
    """Bounded slot intent, not independence, review or supply authority."""
    schema_version: Literal["finite_slot_allocation_v2"] = "finite_slot_allocation_v2"
    target_id: TargetId
    family_id: str
    family_definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_id: str
    slot: Slot
    purpose: Literal["exercise", "knowledge_check", "remediation"]
    clause_refs: tuple[FiniteClauseReferenceV1, ...] = Field(min_length=3, max_length=3)
    guidance: Literal["unguided", "state_table_and_localization_hints"]
    binding_requirement: Literal["native_scope", "purpose_child_scope"]

    @property
    def definition_hash(self) -> str:
        return canonical_hash({"domain": "finite-slot-allocation-v2",
            "payload": checked_model(self, FiniteSlotAllocationV2).model_dump(mode="json")})

    @model_validator(mode="after")
    def registered_semantics(self) -> FiniteSlotAllocationV2:
        family = next((f for f in families_for_course(self.target_id) if f.family_id == self.family_id), None)
        role = self.variant_id.removeprefix(self.target_id + ":")
        remedial = self.slot == "remediation"
        purpose = "remediation" if remedial else "knowledge_check" if self.target_id == "python-kc-binding-v1" else "exercise"
        if (family is None or self.family_definition_hash != family.definition_hash
                or (remedial and self.target_id == "python-kc-binding-v1" and family.task_kind != "diagnose")
                or self.clause_refs != family.clause_refs or self.variant_id != self.target_id + ":" + role
                or _SLOT_ROLES.get(role) != self.slot or self.purpose != purpose
                or self.guidance != ("state_table_and_localization_hints" if remedial else "unguided")
                or self.binding_requirement != ("purpose_child_scope" if remedial else "native_scope")):
            raise ValueError("finite_explicit_allocation_mismatch")
        return self


def build_finite_slot_allocation(*, target_id: TargetId, family_id: str, slot: Slot,
                                 slot_index: int = 1) -> FiniteSlotAllocationV2:
    """Use any supported family in a purpose-compatible one-of-five slot."""
    family = next((f for f in families_for_course(target_id) if f.family_id == family_id), None)
    if family is None or type(slot_index) is not int or slot_index not in ((1,) if slot == "remediation" else (1, 2)):
        raise ValueError("finite_explicit_allocation_invalid")
    role = "guided-remediation" if slot == "remediation" else f"{slot}-{slot_index}"
    remedial = slot == "remediation"
    return FiniteSlotAllocationV2(target_id=target_id, family_id=family_id, family_definition_hash=family.definition_hash,
        variant_id=target_id + ":" + role, slot=slot,
        purpose="remediation" if remedial else "knowledge_check" if target_id == "python-kc-binding-v1" else "exercise",
        clause_refs=family.clause_refs, guidance="state_table_and_localization_hints" if remedial else "unguided",
        binding_requirement="purpose_child_scope" if remedial else "native_scope")


def resolve_finite_slot_allocation(*, target_id: TargetId, variant_id: str,
        public_spec_version: str = FACTORY_VERSION,
        allocation: FiniteSlotAllocationV1 | FiniteSlotAllocationV2 | None = None,
) -> FiniteSlotAllocationV1 | FiniteSlotAllocationV2:
    if public_spec_version not in (FACTORY_VERSION, PYTHON_FACTORY_VERSION_V2, FLEXIBLE_FACTORY_VERSION) or (
            public_spec_version == PYTHON_FACTORY_VERSION_V2 and target_id != "python-state-update-v1"):
        raise ValueError("finite_public_spec_version_invalid")
    legacy = next((a for a in initial_slot_allocations(target_id) if a.variant_id == variant_id), None)
    if allocation is None:
        if legacy is None:
            raise ValueError("finite_allocation_unregistered")
        return legacy
    allocation = (checked_model(allocation, FiniteSlotAllocationV2) if type(allocation) is FiniteSlotAllocationV2
                  else checked_model(allocation, FiniteSlotAllocationV1))
    if allocation.target_id != target_id or allocation.variant_id != variant_id:
        raise ValueError("finite_allocation_scope_mismatch")
    if public_spec_version != FLEXIBLE_FACTORY_VERSION and allocation != legacy:
        raise ValueError("finite_allocation_unregistered")
    return allocation


def _blueprint_key(target_id: TargetId, allocation: FiniteSlotAllocationV1 | FiniteSlotAllocationV2,
                   seed: int, public_spec_version: str) -> str:
    role = allocation.variant_id.rsplit(":", 1)[1]
    family = ".family-" + allocation.family_id.rsplit(":", 1)[1] if public_spec_version == FLEXIBLE_FACTORY_VERSION else ""
    return f"finite.{target_id}.{role}{family}.s{seed}"


def allocation_from_blueprint(blueprint: LearningItemBlueprintV1, target_id: TargetId,
                             ) -> tuple[FiniteSlotAllocationV1 | FiniteSlotAllocationV2, int]:
    """Decode and revalidate a canonical factory key; never infer from prose."""
    prefix = "finite." + target_id + "."
    roles = "|".join(_SLOT_ROLES)
    family_pattern = r"\.family-([a-z_]+)" if blueprint.version == FLEXIBLE_FACTORY_VERSION else ""
    match = re.fullmatch(re.escape(prefix) + f"({roles})" + family_pattern + r"\.s([0-9]{1,3})", blueprint.blueprint_key)
    if match is None:
        raise ValueError("finite_blueprint_allocation_invalid")
    role, seed = match[1], int(match[3] if family_pattern else match[2])
    allocation = None
    if family_pattern:
        slot = cast(Slot, _SLOT_ROLES[role])
        allocation = build_finite_slot_allocation(target_id=target_id, family_id=target_id + ":" + match[2],
            slot=slot, slot_index=1 if slot == "remediation" else int(role[-1]))
    resolved = resolve_finite_slot_allocation(target_id=target_id, variant_id=target_id + ":" + role,
        public_spec_version=blueprint.version, allocation=allocation)
    if seed > 255 or blueprint.blueprint_key != _blueprint_key(target_id, resolved, seed, blueprint.version):
        raise ValueError("finite_blueprint_allocation_invalid")
    return resolved, seed


class FiniteCandidateSpecV1(StorageContract):
    """Public specification and declaration bindings, not a source/review receipt."""
    schema_version: Literal["finite_candidate_spec_v1"] = "finite_candidate_spec_v1"
    target_id: TargetId
    target_definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    family_definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    allocation: FiniteSlotAllocationV1 | FiniteSlotAllocationV2
    seed: int = Field(ge=0, le=255)
    blueprint: LearningItemBlueprintV1
    public_template: LearningItemPublicV1
    coverage_blueprint: CoverageBlueprintV1
    # Exact public parameters for a later descriptor/scoring owner, no outcomes.
    python_goal: PythonStateTarget | None = None
    sql_target: SqlitePredicateTargetV1 | None = None

    @property
    def specification_hash(self) -> str:
        return canonical_hash(checked_model(self, FiniteCandidateSpecV1).model_dump(mode="json"))


def _references(materials: tuple[PublicMaterialV2, ...], target_id: TargetId) -> tuple[LearningItemSourceReferenceV1, ...]:
    if not 1 <= len(materials) <= 12:
        raise ValueError("finite_material_count_invalid")
    references: dict[tuple[str, str, str], LearningItemSourceReferenceV1] = {}
    for raw in materials:
        material = require_exact_material(raw)
        if type(material.binding) is not PublicCourseEvidenceBindingV1 or material.binding.target_id != target_id:
            raise ValueError("finite_native_source_target_mismatch")
        validate_public_course_request(material.binding, material.access_request, material.exact_claims)
        coordinate = material.binding.evidence[0]
        ref = LearningItemSourceReferenceV1(source_id=coordinate.binding.source_handle,
            source_version=coordinate.binding.document_revision, locator=coordinate.chunk_id,
            content_hash=coordinate.binding.document_hash)
        key = (ref.source_id, ref.source_version, ref.locator)
        if key in references and references[key] != ref:
            raise ValueError("finite_source_reference_conflict")
        references[key] = ref
    return tuple(references.values())


def _python_task_v2(goal: PythonStateTarget, starter: str, guided: bool) -> tuple[PythonStateTarget, str, LearningItemCodeContentV1]:
    """Describe the existing closed event shapes, without reference code/outcomes."""
    kind = goal.task_kind
    if kind == "accumulate":
        steps = (
            "初始角色为 total、increase、decrease，分别取 initial、increase、decrease 的给定整数值。"
            "初始化之后恰有两次写回 total：先读取 total 与 increase 相加，再读取更新后的 total 与 decrease 相减；"
            "两次都必须读取命名变量，不以其数值替代。最后只输出 total。"
            "这两次更新可用简单赋值或对应的 +=、-=；不允许临时变量、两项同时赋值或额外无效赋值。"
        )
    elif kind == "refresh":
        steps = (
            "初始角色为 price、qty，分别取 price、initial_qty 的给定整数值。"
            "初始化之后，先且仅先用当前 price 与 qty 的乘积给 subtotal 赋值；"
            "再用 updated_qty 的给定整数文字量直接给 qty 赋值，不用增量或其他表达式代替。"
            "接着刷新只有两种形式：重新读取 price 与 qty 的乘积直接写入 subtotal；"
            "或先将该乘积写入 refreshed，再把 refreshed 的当前值写入 subtotal。最后只输出 subtotal。"
            "这些步骤均为简单赋值，不使用 +=/-= 或两项同时赋值，也不添加其他步骤。"
        )
    elif kind == "swap":
        steps = (
            "初始角色为 left、right，分别取同名参数的给定整数值。"
            "初始化之后交换两个原值，只选一种形式：用三次简单赋值，先以 saved 保存任意一侧的原值，"
            "再把另一侧的当前值赋给该侧，最后从 saved 取回原值赋给另一侧；"
            "或者只用一次两项同时赋值交换 left 与 right，两项的书写次序可对调。"
            "不混合两种形式，不使用算术交换或 +=/-=，不添加其他赋值。最后按 left、right 顺序输出。"
        )
    else:
        steps = (
            "初始角色为 source、target、amount，分别取同名参数的给定整数值。"
            "初始化之后，从 source 扣除 amount 并把同一 amount 加入 target，始终读取命名变量且不改变 amount。"
            "两侧可分别写回（先后次序不限，使用简单赋值或对应的 -=、+=），"
            "也可只用一次两项同时赋值，分别读取更新前的两侧与 amount，两项书写次序不限。"
            "然后依次输出最终 source、target、两者之和；该和可在输出中直接相加，"
            "或只在两侧更新之后用一次简单赋值存入 total 再输出。除此之外不添加赋值或计算步骤。"
        )
    instruction = (
        "本题只接受以下有限状态步骤，不要求支持任意数值等价的 Python 程序。"
        "先将每个初始角色各用一条简单赋值绑定到给定整数文字量；这些独立初始化可重排，"
        "但不可省略、重复、合并为链式赋值或两项同时赋值，也不可用计算表达式替代给定整数文字量。"
        + steps +
        "仅使用题面命名变量；除明确允许的选择外不得增加临时变量、重复写入或 no-op。"
        "读取变量时不能用恰好相等的整数替代。表达式只使用上述步骤指定的单层加减乘；"
        "允许空白、注释、括号、整数文字量的正负号，以及单层加法/乘法的两个操作数交换，"
        "不允许代数改写、分支、循环、函数、导入或其他调用。"
        "最后恰好调用一次 print，不指定 keyword，以空格分隔规定输出并换行；不能写死最终值。"
        "编辑并提交完整程序。完成项模式仅作赋值符号数量的语法提示，注释等也可能匹配它；"
        "它不判定变量、顺序、数值或正确性，真正评分仍同时检查上述状态目标和输出。"
    )
    if guided:
        instruction += ("\n先在草稿中建立状态表：列出初始、首次求值、qty 更新后、subtotal 刷新后四个时刻；"
                        "每格自行填写，并标记发生变化的赋值目标。对照当前右值定位需刷新的位置，再补全代码。")
    instruction += "\n公开目标参数（只定义本题，不含预期结果）：\n~~~json\n" + json.dumps(
        goal.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n~~~"
    # Necessary lexical anchor for every accepted shape (including parentheses,
    # tuple updates and normalized identifiers), NOT a semantic test. Disjoint
    # '=' segments are anchored to avoid scanning/backtracking at every position.
    minimum_assignments = {"accumulate": 5, "refresh": 5, "swap": 3, "transfer": 4}[kind]
    content = LearningItemCodeContentV1.model_validate(dict(type="code", language_id="python", editor_language="python",
        exercise_type="code_completion", starter_code=starter, required_patterns=(), code_blanks=({
            "blank_key": "state_update",
            "expected_concept": f"补入本题所需状态写入；模式仅提示完整程序至少含 {minimum_assignments} 个赋值符号，不证明状态目标或正确性",
            "acceptable_patterns": ({"type": "regex", "value": rf"\A(?:[^=]*=){{{minimum_assignments}}}"},),
            "is_core": True},)))
    return goal, instruction, content


def _python_task(kind: str, seed: int, guided: bool, *, public_spec_version: str = FACTORY_VERSION) -> tuple[PythonStateTarget, str, LearningItemCodeContentV1]:
    if public_spec_version not in (FACTORY_VERSION, PYTHON_FACTORY_VERSION_V2, FLEXIBLE_FACTORY_VERSION):
        raise ValueError("finite_python_public_spec_version_invalid")
    # Closed bounded parameters, derived from registered task roles. No submitted
    # source is parsed/evaluated and no private fixture solution is selected.
    offset = seed + (17 if guided else 0)
    parameters = {
        "accumulate": ({"total": "total", "increase": "increase", "decrease": "decrease"},
                       {"initial": 10 + offset, "increase": 4 + offset % 3, "decrease": 3}),
        "refresh": ({"price": "price", "qty": "qty", "subtotal": "subtotal", "saved": "refreshed"},
                    {"price": 2 + offset % 4, "initial_qty": 3 + offset % 3, "updated_qty": 5 + offset % 3}),
        "swap": ({"left": "left", "right": "right", "saved": "saved"},
                 {"left": 2 + offset % 4, "right": 7 + offset % 5}),
        "transfer": ({"source": "source", "target": "target", "amount": "amount", "total": "total"},
                     {"source": 9 + offset % 7, "target": 1 + offset % 4, "amount": 3 + offset % 3}),
    }
    variables, values = parameters[kind]
    goal = parse_python_state_target(dict(goal_contract_id="python-state-update-v1", task_kind=kind,
                                          variables=variables, values=values))
    if kind == "accumulate":
        instruction = "先将 increase 纳入 total，再从更新后的 total 扣除 decrease；每一步都实际更新同一累计变量，最后仅输出 total。"
        starter = f"total = {values['initial']}\nincrease = {values['increase']}\ndecrease = {values['decrease']}\n# 在此补全状态更新\nprint(total)"
    elif kind == "refresh":
        instruction = ("先以初始 price 与 qty 的乘积计算 subtotal，随后 qty 改为题面给定的新值。"
                       "使用当前 price 与 qty 重新求值并更新 subtotal，最后仅输出 subtotal。可使用临时变量 refreshed。")
        starter = (f"price = {values['price']}\nqty = {values['initial_qty']}\nsubtotal = price * qty\n"
                   f"qty = {values['updated_qty']}\n# 在此补全依赖值刷新\nprint(subtotal)")
    elif kind == "swap":
        instruction = ("交换 left 与 right 保存的两个原值，不能丢失任一原值。可使用临时变量 saved 后顺序赋值，"
                       "或两项同时赋值。最后按 left、right 的顺序输出最终值。")
        starter = f"left = {values['left']}\nright = {values['right']}\n# 在此补全交换\nprint(left, right)"
    else:
        instruction = ("从 source 向 target 转移 amount。两侧都必须使用同一未改变的转移量，一减一加，保持总量不变。"
                       "可依次更新（次序不限）或两项同时赋值。最后依次输出 source、target 及它们的最终总量；"
                       "总量可直接求和或先保存到 total。")
        starter = (f"source = {values['source']}\ntarget = {values['target']}\namount = {values['amount']}\n"
                   "# 在此补全两侧状态更新\nprint(source, target, source + target)")
    if public_spec_version == FLEXIBLE_FACTORY_VERSION:
        goal, instruction, content = _python_task_v2(goal, starter, False)
        if guided:
            instruction += "\n先自行列出每一步的变量状态表，定位读取值与写回目标，再补全程序；不预给最终状态或答案。"
        return goal, instruction, content
    if public_spec_version == PYTHON_FACTORY_VERSION_V2:
        return _python_task_v2(goal, starter, guided)
    instruction += ("保留给定初始值和规定更新顺序；仅使用题面命名变量、整数、顶层简单赋值、两项同时赋值或 +=/-=。"
        "表达式限单层加减乘；不使用分支、循环、函数、导入或其他调用。最后只调用一次 print，不指定 keyword，"
        "以空格分隔输出并换行；不能写死最终值。允许空白、注释、括号及加法/乘法交换律。")
    if guided:
        instruction += ("\n先在草稿中建立状态表：列出初始、首次求值、qty 更新后、subtotal 刷新后四个时刻；"
                        "每格自行填写，并标记发生变化的赋值目标。对照当前右值定位需刷新的位置，再补全代码。")
    instruction += "\n公开目标参数（只定义本题，不含预期结果）：\n~~~json\n" + json.dumps(
        goal.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n~~~"
    content = LearningItemCodeContentV1.model_validate(dict(type="code", language_id="python", editor_language="python",
        exercise_type="code_completion", starter_code=starter, required_patterns=(), code_blanks=({
            "blank_key": "state_update", "expected_concept": "按当前变量值补全状态更新，并输出指定的最终变量",
            # Legacy syntactic anchor only; it is NOT a goal/coverage/scoring proof.
            "acceptable_patterns": ({"type": "regex", "value": r"\bprint\b"},), "is_core": True},)))
    return goal, instruction, content


def build_finite_candidate_spec(
    *, target_id: TargetId, variant_id: str, seed: int, item_key: str, version: str,
    materials: tuple[PublicMaterialV2, ...], runtime_profile_hash: str | None,
    scorer_version: str, assistance_policy_hash: str, policy_version: str,
    difficulty_profile: LearningItemDifficultyProfileV1, publication_policy: LearningItemPublicationPolicyV1,
    public_spec_version: str = FACTORY_VERSION,
    allocation: FiniteSlotAllocationV1 | FiniteSlotAllocationV2 | None = None,
) -> FiniteCandidateSpecV1:
    """Build a bounded allocation intent; no source-current grant.

    Python/SQL runtime_profile_hash is the caller's current lock identity. KC
    requires None and derives a static-contract hash instead of faking a lock.
    Risk/difficulty/publication policy are explicit trusted inputs, not inferred
    from a family name or weakened from a prior candidate's review outcome.
    """
    target = get_finite_course_target(target_id)
    if type(seed) is not int or not 0 <= seed <= 255:
        raise ValueError("finite_seed_invalid")
    allocation = resolve_finite_slot_allocation(target_id=target_id, variant_id=variant_id,
        public_spec_version=public_spec_version, allocation=allocation)
    if public_spec_version == FLEXIBLE_FACTORY_VERSION and type(allocation) is FiniteSlotAllocationV1:
        role = allocation.variant_id.rsplit(":", 1)[1]
        allocation = build_finite_slot_allocation(target_id=target_id, family_id=allocation.family_id,
            slot=allocation.slot, slot_index=1 if role == "guided-remediation" else int(role[-1]))
    family = next(f for f in families_for_course(target_id) if f.family_id == allocation.family_id)
    guided = allocation.slot == "remediation"
    references = _references(materials, target_id)
    difficulty = checked_model(difficulty_profile, LearningItemDifficultyProfileV1)
    publication = checked_model(publication_policy, LearningItemPublicationPolicyV1)
    if difficulty.base != difficulty.computed_base:
        raise ValueError("finite_difficulty_inconsistent")
    runtime_id = target.assessment.runtime_profile_id
    if runtime_id is None:
        if runtime_profile_hash is not None:
            raise ValueError("finite_static_runtime_lock_denied")
        runtime_hash = canonical_hash({"runtime": "static-exact-v1", "scorer_version": scorer_version,
                                       "assessment_contract": target.assessment.assessment_contract_version})
    else:
        if runtime_profile_hash is None:
            raise ValueError("finite_runtime_lock_required")
        runtime_hash = runtime_profile_hash
    scope = SupplyScopeV1(course_family="finite." + target_id, course_version="1.0",
        knowledge_key="finite." + target_id, language_id=target.language_id, subject_id=target.subject_id,
        subject_version="1.0", required_facets=target.required_facets,
        dialect="sqlite" if target.language_id == "sql" else None,
        runtime_profile_id=runtime_id or "static-exact-v1", runtime_profile_hash=runtime_hash,
        item_kind=LearningItemKind(target.assessment.item_kind), purpose=LearningItemPurpose(allocation.purpose),
        interaction=LearningItemInteraction(target.assessment.interaction), required_capabilities=target.required_capabilities,
        assessment_contract_version=target.assessment.assessment_contract_version, scorer_version=scorer_version,
        assistance_policy_hash=assistance_policy_hash)
    coverage = CoverageBlueprintV1(scope=scope,
        objective_hash=canonical_hash({"goal": target.goal_text, "clauses": [c.definition_hash for c in target.clauses]}),
        clauses=tuple(ObjectiveClauseV1(clause_id=c.clause_id.lower(), clause_hash=c.definition_hash) for c in target.clauses),
        matrix_hash=build_support_matrix().matrix_hash, policy_version=policy_version)
    interactions = (scope.interaction,) if runtime_id is None else (scope.interaction, LearningItemInteraction.RUN)
    blueprint = LearningItemBlueprintV1(blueprint_key=_blueprint_key(target_id, allocation, seed, public_spec_version),
        version=public_spec_version, knowledge_key=scope.knowledge_key, item_kind=scope.item_kind, purpose=scope.purpose,
        language_id=target.language_id, difficulty_profile=difficulty, required_capabilities=target.required_capabilities,
        runtime_profile_id=None if runtime_id is None else target.assessment.execution_contract,
        allowed_interactions=interactions, publication_policy=publication, source_references=references)
    python_goal, sql_target, instruction, public_content = _public_task(
        target_id, family.task_kind, seed, guided, public_spec_version)
    public = LearningItemPublicV1(item_key=item_key, version=version, kind=scope.item_kind, purpose=scope.purpose,
        title=f"{target.display_id} · {family.task_kind}" + (" · 引导补救" if guided else ""),
        difficulty=difficulty.base, instruction_markdown=instruction, allowed_interactions=interactions,
        source_references=references, content=public_content)
    return FiniteCandidateSpecV1(target_id=target_id, target_definition_hash=target.definition_hash,
        family_definition_hash=family.definition_hash, allocation=allocation, seed=seed,
        blueprint=blueprint, public_template=public, coverage_blueprint=coverage,
        python_goal=python_goal, sql_target=sql_target)


def _public_task(target_id: TargetId, task_kind: str, seed: int, guided: bool, public_spec_version: str,
                 ) -> tuple[PythonStateTarget | None, SqlitePredicateTargetV1 | None, str, LearningItemPublicContentV1]:
    python_goal, sql_target = None, None
    public_content: LearningItemPublicContentV1
    if target_id == "python-state-update-v1":
        python_goal, instruction, public_content = _python_task(task_kind, seed, guided, public_spec_version=public_spec_version)
    elif target_id == "sqlite-predicate-order-v1":
        data: dict[str, object] = {"task_kind": task_kind}
        if task_kind == "conjunction":
            data["min_score"] = 60 + seed
        elif task_kind == "keyset_after":
            data.update(cut_score=70 + seed, cut_id=4 + seed)
        sql_target = parse_sqlite_target(data)
        task = sqlite_public_task(sql_target)
        instruction = task.instruction
        if guided:
            if public_spec_version == FLEXIBLE_FACTORY_VERSION:
                instruction += "\n先自行逐行记录本题条件的判断，再核对规定的排序字段与方向；表格和筛选结果由你填写。"
            else:
                instruction += ("\n先画空表，逐行检查 override_flag 是否为 NULL，再填写选用字段、有效值和入选判断；"
                                "随后检查 priority 的 NULL 位置及同优先级的 id 次序。表格由你填写，不预给筛选结果。")
        sql_content = task.content.model_dump(mode="json")
        for table in sql_content["public_dataset"]["tables"]:
            for index, row in enumerate(table["rows"]):
                row[1] = f"entry-{seed + (17 if guided else 0)}-{index + 1}"
        from app.services.learning.item_bank.contracts import LearningItemSqlContentV2

        public_content = LearningItemSqlContentV2.model_validate_json(json.dumps(sql_content))
    else:
        # Dedicated public getter: never pass PythonKcFixtureV1 or exercise helper
        # output (CURATED_FIXTURE/REJECTED) into a provider/publication envelope.
        kc = python_kc_public_content(cast(KcTaskKind, task_kind), guided=guided)
        options = kc.options[seed % 4:] + kc.options[:seed % 4]
        kc = kc.model_copy(update={"options": tuple(option.model_copy(update={"option_id": f"choice-{i + 1}"})
                                                    for i, option in enumerate(options))})
        public_content = kc
        instruction = "阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。"
    if public_spec_version == FLEXIBLE_FACTORY_VERSION:
        instruction = _CORE_START + "\n" + instruction + "\n" + _CORE_END
    return python_goal, sql_target, instruction, public_content


def build_finite_generation_request(
    spec: FiniteCandidateSpecV1, *, candidate_id: UUID, profile: FrozenProfileSnapshot,
    limits: GenerationLimitsV2, materials: tuple[PublicMaterialV2, ...],
) -> GenerationRequestV2:
    """Rebuild exact registered public specification, then use the unchanged V2 DTO.

    The spec envelope/seed/fixture internals are not dumped into the author prompt.
    Source currency still belongs to the concrete same-connection shared pipeline.
    """
    spec = checked_model(spec, FiniteCandidateSpecV1)
    scope = spec.coverage_blueprint.scope
    expected = build_finite_candidate_spec(target_id=spec.target_id, variant_id=spec.allocation.variant_id,
        seed=spec.seed, item_key=spec.public_template.item_key, version=spec.public_template.version, materials=materials,
        runtime_profile_hash=None if spec.blueprint.runtime_profile_id is None else scope.runtime_profile_hash,
        scorer_version=scope.scorer_version, assistance_policy_hash=scope.assistance_policy_hash,
        policy_version=spec.coverage_blueprint.policy_version, difficulty_profile=spec.blueprint.difficulty_profile,
        publication_policy=spec.blueprint.publication_policy, public_spec_version=spec.blueprint.version,
        allocation=spec.allocation)
    if spec != expected:
        raise ValueError("finite_specification_mismatch")
    return GenerationRequestV2(candidate_id=candidate_id, scope_hash=scope.scope_hash, demand_binding=None,
        item_key=spec.public_template.item_key, version=spec.public_template.version, blueprint=spec.blueprint,
        public_template=spec.public_template, profile=checked_model(profile, FrozenProfileSnapshot),
        limits=checked_model(limits, GenerationLimitsV2), materials=materials)


def check_finite_public_spec(public: LearningItemPublicV1, spec: FiniteCandidateSpecV1) -> None:
    """Strict public-only reconstruction; presentation flexibility is NOT review.

    V3 changes ONLY title/instruction. The complete deterministic task block is
    still mandatory once, while introductory/concluding prose is untrusted and
    must undergo blind solve, ambiguity, adversarial and all six review roles.
    """
    public, spec = checked_model(public, LearningItemPublicV1), checked_model(spec, FiniteCandidateSpecV1)
    public_task_from_blueprint(spec.blueprint, spec.public_template, spec.target_id)
    target = get_finite_course_target(spec.target_id)
    allocation = resolve_finite_slot_allocation(target_id=spec.target_id, variant_id=spec.allocation.variant_id,
        public_spec_version=spec.blueprint.version, allocation=spec.allocation)
    family = next(f for f in families_for_course(spec.target_id) if f.family_id == allocation.family_id)
    goal, sql_target, instruction, content = _public_task(spec.target_id, family.task_kind, spec.seed,
        allocation.slot == "remediation", spec.blueprint.version)
    if (spec.target_definition_hash != target.definition_hash or spec.family_definition_hash != family.definition_hash
            or spec.python_goal != goal or spec.sql_target != sql_target or spec.public_template.content != content
            or spec.public_template.instruction_markdown != instruction
            or spec.blueprint.blueprint_key != _blueprint_key(spec.target_id, allocation, spec.seed, spec.blueprint.version)):
        raise ValueError("finite_candidate_specification_mismatch")
    check_finite_public_presentation(public, spec.public_template, public_spec_version=spec.blueprint.version)


def check_finite_public_presentation(public: LearningItemPublicV1, expected: LearningItemPublicV1,
                                     *, public_spec_version: str) -> None:
    """Shared field fence; callers must also reconstruct the registered task."""
    public, expected = checked_model(public, LearningItemPublicV1), checked_model(expected, LearningItemPublicV1)
    if public_spec_version not in (FACTORY_VERSION, PYTHON_FACTORY_VERSION_V2, FLEXIBLE_FACTORY_VERSION):
        raise ValueError("finite_public_spec_version_invalid")
    if public_spec_version != FLEXIBLE_FACTORY_VERSION:
        if public != expected:
            raise ValueError("finite_candidate_specification_mismatch")
        return
    # No permissive content reserialization, option/schema/dataset/hint changes.
    if public.model_dump(mode="json", exclude={"title", "instruction_markdown"}) != expected.model_dump(
            mode="json", exclude={"title", "instruction_markdown"}):
        raise ValueError("finite_candidate_specification_mismatch")
    prose = public.instruction_markdown
    instruction = expected.instruction_markdown
    if (prose.count(_CORE_START) != 1 or prose.count(_CORE_END) != 1 or prose.count(instruction) != 1):
        raise ValueError("finite_public_task_core_mismatch")


def check_finite_source_spec(source: LearningItemSourceV1, spec: FiniteCandidateSpecV1) -> None:
    """Reusable exact blueprint and version-aware public binding (no private IO)."""
    source, spec = checked_model(source, LearningItemSourceV1), checked_model(spec, FiniteCandidateSpecV1)
    if source.blueprint != spec.blueprint:
        raise ValueError("finite_candidate_specification_mismatch")
    check_finite_public_spec(source.public, spec)


def public_task_from_blueprint(blueprint: LearningItemBlueprintV1, public: LearningItemPublicV1,
        target_id: TargetId) -> tuple[PythonStateTarget | None, SqlitePredicateTargetV1 | None, LearningItemPublicV1]:
    """Rebuild public semantics without inventing missing scope/runtime authority."""
    blueprint, public = checked_model(blueprint, LearningItemBlueprintV1), checked_model(public, LearningItemPublicV1)
    allocation, seed = allocation_from_blueprint(blueprint, target_id)
    target = get_finite_course_target(target_id)
    family = next(f for f in families_for_course(target_id) if f.family_id == allocation.family_id)
    guided = allocation.slot == "remediation"
    goal, sql_target, instruction, content = _public_task(target_id, family.task_kind, seed, guided, blueprint.version)
    if (blueprint.knowledge_key != "finite." + target_id or blueprint.language_id != target.language_id
            or blueprint.item_kind.value != target.assessment.item_kind or blueprint.purpose.value != allocation.purpose
            or blueprint.runtime_profile_id != (target.assessment.execution_contract if target.assessment.runtime_profile_id is not None else None)
            or blueprint.required_capabilities != target.required_capabilities
            or public.kind != blueprint.item_kind or public.purpose != blueprint.purpose
            or public.difficulty != blueprint.difficulty_profile.base
            or public.allowed_interactions != blueprint.allowed_interactions
            or public.source_references != blueprint.source_references):
        raise ValueError("finite_public_request_blueprint_mismatch")
    canonical_public = public.model_copy(update={"title": f"{target.display_id} · {family.task_kind}" + (" · 引导补救" if guided else ""),
        "instruction_markdown": instruction, "content": content, "hints": (), "remediation_item_key": None})
    check_finite_public_presentation(public, canonical_public, public_spec_version=blueprint.version)
    return goal, sql_target, canonical_public


def check_finite_public_request(request: GenerationRequestV2) -> LearningItemPublicV1:
    """Validate the real producer request, return its canonical PUBLIC task only."""
    request = checked_model(request, GenerationRequestV2)
    target_ids: tuple[TargetId, ...] = ("python-state-update-v1", "sqlite-predicate-order-v1", "python-kc-binding-v1")
    target_id = next((t for t in target_ids if request.blueprint.blueprint_key.startswith("finite." + t + ".")), None)
    if target_id is None or request.public_template is None:
        raise ValueError("finite_public_request_required")
    if request.public_template.item_key != request.item_key or request.public_template.version != request.version:
        raise ValueError("finite_public_request_identity_mismatch")
    if _references(request.materials, target_id) != request.blueprint.source_references:
        raise ValueError("finite_public_request_source_mismatch")
    _, _, public = public_task_from_blueprint(request.blueprint, request.public_template, target_id)
    return public

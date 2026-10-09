"""Exact closed curriculum definitions; these are NOT frozen learner scopes."""
from types import MappingProxyType

from .finite_targets.contracts import (
    FiniteAssessmentDeclarationV1,
    FiniteClauseV1,
    FiniteCourseTargetV1,
)

_TARGETS = (
    FiniteCourseTargetV1(
        target_id="python-state-update-v1", display_id="PY-STATE-01",
        goal_text=("在有限顺序程序中，依据当前变量值计算中间结果，并按数据依赖顺序更新状态，"
                   "输出满足题面不变量的最终状态；不能以写死输出替代赋值过程。"),
        language_id="python", subject_id="route.python", required_facets=("fundamentals",),
        required_capabilities=("python.assignment",),
        clauses=(
            FiniteClauseV1(clause_id="PY-C1", statement=(
                "右值来自题面指定的当前或保存变量，真实执行赋值，不通过直接输出常量替代。")),
            FiniteClauseV1(clause_id="PY-C2", statement=(
                "更新顺序保留目标所需中间信息，实际状态满足该任务的关系不变量。")),
            FiniteClauseV1(clause_id="PY-C3", statement=(
                "仅输出明确指定的最终值或元组，标准输出与目标状态均正确。")),
        ),
        assessment=FiniteAssessmentDeclarationV1(
            item_kind="code", content_type="code_completion", interaction="edit", purpose="exercise",
            assessment_contract_version="python-state-update-v1", scorer_domain="python-state-update-v1",
            execution_contract="python_stdout_test", runtime_profile_id="python-stdout-v1",
        ),
    ),
    FiniteCourseTargetV1(
        target_id="sqlite-predicate-order-v1", display_id="SQL-PRED-ORDER-01",
        goal_text=("对有限SQLite单表，准确实现题面行选择条件，保持投影结果的多重集语义，"
                   "并按明确的全序输出；能区分组合条件、缺失值与排序边界。"),
        language_id="sql", subject_id="route.sql", required_facets=("queries",),
        required_capabilities=("sql.select.where", "sql.order_by"),
        clauses=(
            FiniteClauseV1(clause_id="SQL-C1", statement=(
                "精确实现题面谓词，包括该任务明确声明的NULL语义。")),
            FiniteClauseV1(clause_id="SQL-C2", statement=(
                "投影、列身份及匹配行多重性正确，不随意去重。")),
            FiniteClauseV1(clause_id="SQL-C3", statement=(
                "结果遵循稳定、完整的指定全序，包括相同主排序键时的次排序键。")),
        ),
        assessment=FiniteAssessmentDeclarationV1(
            item_kind="sql", content_type="sql_v2", interaction="query", purpose="exercise",
            assessment_contract_version="sqlite-predicate-order-v1", scorer_domain="sqlite-predicate-order-v1",
            execution_contract="sql_query_test", runtime_profile_id="sqlite-query-v1",
        ),
    ),
    FiniteCourseTargetV1(
        target_id="python-kc-binding-v1", display_id="PY-KC-BIND-01",
        goal_text=("根据顺序赋值解释名字与值的关系：右值在赋值时求值，重绑定只改变目标名字，"
                   "已经保存的值或派生值不自动随之更新；能通过追踪、诊断、修复和反例说明行为。"),
        language_id="python", subject_id="route.python", required_facets=("fundamentals",),
        required_capabilities=("python.assignment",),
        clauses=(
            FiniteClauseV1(clause_id="KC-C1", statement="正确判断指定时刻的右值。"),
            FiniteClauseV1(clause_id="KC-C2", statement="区分源名字重绑定与已保存或派生的值。"),
            FiniteClauseV1(clause_id="KC-C3", statement=(
                "用任务所要求的唯一正确选项说明可观察结果与因果。")),
        ),
        assessment=FiniteAssessmentDeclarationV1(
            item_kind="knowledge_check", content_type="single_choice", interaction="respond",
            purpose="knowledge_check", assessment_contract_version="python-kc-binding-v1",
            scorer_domain="python-kc-binding-v1", execution_contract="knowledge_check_v1",
            runtime_profile_id=None,
        ),
    ),
)
_REGISTRY: MappingProxyType[str, FiniteCourseTargetV1] = MappingProxyType({
    target.target_id: target for target in _TARGETS
})


def get_finite_course_target(target_id: str) -> FiniteCourseTargetV1:
    """Look up a program ID exactly. Text/capabilities/display IDs are not aliases."""
    if type(target_id) is not str or target_id not in _REGISTRY:
        raise KeyError("unknown finite course target")
    return _REGISTRY[target_id]


def finite_course_targets() -> tuple[FiniteCourseTargetV1, ...]:
    return _TARGETS


def finite_node_description(target_id: str) -> str:
    """Exact semantic transport for D's existing 300-character description.

    Produces no node, scope or permission. The actual planner must freeze these
    bytes, language and capabilities before a course can map. No fuzzy aliases.
    """
    target = get_finite_course_target(target_id)
    text = target.display_id + "：" + target.goal_text + " " + " ".join(
        c.clause_id + "：" + c.statement for c in target.clauses)
    if len(text) > 300:
        raise ValueError("finite contract exceeds compact D description")
    return text

"""Source-controlled curated MVP exercise fixtures."""
from __future__ import annotations

from dataclasses import dataclass

from app.services.learning.practice.contracts import (
    ExercisePrivateRubric,
    ExerciseSourceKind,
    ExerciseType,
    ExerciseVersion,
)
from app.services.learning.practice.quality import require_exercise_quality


@dataclass(frozen=True, slots=True)
class CuratedExerciseFixture:
    exercise: ExerciseVersion
    rubric: ExercisePrivateRubric


def _fixture(
    *,
    language_id: str,
    exercise_key: str,
    exercise_type: ExerciseType,
    title: str,
    prompt: str,
    starter: str,
    capability: str,
    runtime_profile_id: str,
    reference: str,
) -> CuratedExerciseFixture:
    exercise = ExerciseVersion(
        language_id=language_id,
        exercise_key=exercise_key,
        exercise_type=exercise_type,
        version="v1",
        source_kind=ExerciseSourceKind.CURATED_FIXTURE,
        title=title,
        learner_prompt={"text": prompt},
        starter_artifact={"content": starter},
        required_capabilities=(capability,),
        runtime_profile_id=runtime_profile_id,
        execution_required=True,
        public_feedback_policy_version="lesson_gate_feedback_v1",
    )
    rubric = ExercisePrivateRubric(
        rubric_version="v1",
        private_test_bundle=(
            {"case_type": "visible", "input": {}, "expected": {"value": reference}, "order_index": 0},
            {"case_type": "hidden", "input": {}, "expected": {"value": reference}, "order_index": 1},
        ),
        reference_answer={"content": reference},
        score_policy={"kind": "all_tests", "threshold": 0.8},
    )
    require_exercise_quality(exercise, rubric)
    return CuratedExerciseFixture(exercise=exercise, rubric=rubric)


CORE_EXERCISE_FIXTURES: tuple[CuratedExerciseFixture, ...] = (
    _fixture(
        language_id="python",
        exercise_key="python.variables.output",
        exercise_type=ExerciseType.CODE_COMPLETION,
        title="输出变量值",
        prompt="补全代码，使程序输出 3。",
        starter="value = 3\nprint(/* 补全 */)",
        capability="python.variables",
        runtime_profile_id="python_stdout_test",
        reference="value",
    ),
    _fixture(
        language_id="javascript",
        exercise_key="javascript.dom.text",
        exercise_type=ExerciseType.BROWSER_PREVIEW,
        title="更新页面文本",
        prompt="补全脚本，把 #answer 的文本设置为 3。",
        starter='<div id="answer"></div>\n<script>/* 补全 */</script>',
        capability="javascript.dom.text_content",
        runtime_profile_id="browser_preview",
        reference='document.querySelector("#answer").textContent = "3";',
    ),
    _fixture(
        language_id="typescript",
        exercise_key="typescript.functions.add",
        exercise_type=ExerciseType.CODE_COMPLETION,
        title="实现带类型的加法函数",
        prompt="实现 add，使 add(1, 2) 返回 3。",
        starter="function add(a: number, b: number): number {\n  // 补全\n}",
        capability="typescript.functions",
        runtime_profile_id="node_typescript_test",
        reference="return a + b;",
    ),
    _fixture(
        language_id="sql",
        exercise_key="sql.select.filter",
        exercise_type=ExerciseType.SQL_QUERY,
        title="筛选已启用记录",
        prompt="查询 users 表中 active = 1 的 name。",
        starter="SELECT /* 补全 */ FROM users WHERE /* 补全 */;",
        capability="sql.select.where",
        runtime_profile_id="sql_query_test",
        reference="SELECT name FROM users WHERE active = 1;",
    ),
)


def fixture_for_language(language_id: str) -> CuratedExerciseFixture | None:
    normalized = language_id.strip().lower()
    return next((item for item in CORE_EXERCISE_FIXTURES if item.exercise.language_id == normalized), None)

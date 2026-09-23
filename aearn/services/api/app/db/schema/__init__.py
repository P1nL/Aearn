"""显式、有序的 PostgreSQL Schema fragment manifest。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEMA_DIRECTORY = Path(__file__).parent
SCHEMA_FRAGMENT_NAMES: tuple[str, ...] = (
    '000_foundation.sql',
    '010_core_learning.sql',
    '020_grounding.sql',
    '030_legacy_messages.sql',
    '040_tutor_runtime.sql',
    '050_tutor_learner_state.sql',
    '060_tutor_conversation.sql',
    '070_learning_tracks.sql',
    '080_lesson_teaching_practice.sql',
    '090_model_review.sql',
    '100_review_context.sql',
    '110_thread_turn_codex.sql',
    '120_learning_artifacts.sql',
    '130_learning_item_bank.sql',
    '140_learning_item_governance.sql',
    '150_tutor_branch_continuation.sql',
    '160_teaching_artifact_commit.sql',
    '170_teaching_demonstrations.sql',
    '180_knowledge_checks.sql',
    '190_model_review_artifacts.sql',
    '200_sql_learning_workspace.sql',
    '210_tutor_branch_supersession.sql',
    '220_plan_catalog_knowledge_scope.sql',
    '230_artifact_authority_supersession.sql',
    '240_deepseek_flash_runtime_cutover.sql',
    '250_source_inspection_artifacts.sql',
)


@dataclass(frozen=True)
class SchemaFragment:
    name: str
    path: Path
    sql: str


def schema_fragment_paths() -> tuple[Path, ...]:
    """按 manifest 顺序返回片段，并拒绝缺失或未登记 SQL。"""

    if len(SCHEMA_FRAGMENT_NAMES) != len(set(SCHEMA_FRAGMENT_NAMES)):
        raise RuntimeError("schema fragment manifest contains duplicate names")
    paths = tuple(SCHEMA_DIRECTORY / name for name in SCHEMA_FRAGMENT_NAMES)
    missing = tuple(path.name for path in paths if not path.is_file())
    if missing:
        raise RuntimeError(f"schema fragment files are missing: {missing}")
    declared = set(SCHEMA_FRAGMENT_NAMES)
    unexpected = tuple(sorted(path.name for path in SCHEMA_DIRECTORY.glob("*.sql") if path.name not in declared))
    if unexpected:
        raise RuntimeError(f"schema fragment files are not declared: {unexpected}")
    return paths


def load_schema_fragments() -> tuple[SchemaFragment, ...]:
    return tuple(
        SchemaFragment(name=path.name, path=path, sql=path.read_text(encoding="utf-8"))
        for path in schema_fragment_paths()
    )


def load_schema_text() -> str:
    """只读组合视图；不得另存为第二份聚合 Schema source。"""

    return "".join(fragment.sql for fragment in load_schema_fragments())

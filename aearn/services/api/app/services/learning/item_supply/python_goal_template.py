"""Versioned public completion presentation; no scoring or source authority.

The goal instruction and protected two-form goal contract remain v1. Only this
new item presentation changes; callers must allocate a new candidate/item key
and supply current source references through the normal generation owner.
"""
from __future__ import annotations

from app.services.learning.item_bank.contracts import LearningItemPublicV1, LearningItemSourceReferenceV1
from app.services.learning.item_supply.sandbox.python_goal_scorer import PYTHON_GOAL_INSTRUCTION
from app.services.learning.item_supply.storage_contracts import checked_model

PYTHON_GOAL_COMPLETION_VERSION = "goal-completion-v2"
PYTHON_GOAL_COMPLETION_STARTER = (
    "numbers = [3, -1, 0, 3]\n"
    "# 保留上面的 numbers 赋值，在下面补全求和并输出总和的代码。\n"
    "# 按题目说明任选一种写法。这是编辑提示，不是自动替换的填空标记。"
)
PYTHON_GOAL_COMPLETION_PATTERNS = (
    "print(sum(numbers))",
    "total = sum(numbers)\nprint(total)",
)


def build_python_goal_completion_template(
    *, item_key: str, source_references: tuple[LearningItemSourceReferenceV1, ...],
) -> LearningItemPublicV1:
    """Public-only fixed template for GenerationRequestV2.public_template.

    Canonical tail examples are not lexical acceptance rules. The legacy blank
    hint matches only the required sum identifier, independent of whitespace or
    comments, so it cannot veto either finite form for formatting differences.
    A hint match alone proves no goal; acceptance still requires unchanged
    sealed AST goal facts and the existing goal-aware stdout scorer.
    This builder does not assert that the supplied references are current.
    """
    references = tuple(checked_model(ref, LearningItemSourceReferenceV1) for ref in source_references)
    return LearningItemPublicV1.model_validate({
        "item_key": item_key, "version": PYTHON_GOAL_COMPLETION_VERSION,
        "kind": "code", "purpose": "exercise", "title": "补全列表求和输出", "difficulty": "D1",
        "instruction_markdown": PYTHON_GOAL_INSTRUCTION,
        "allowed_interactions": ("edit", "run"), "source_references": references,
        "content": {
            "type": "code", "language_id": "python", "editor_language": "python",
            "exercise_type": "code_completion", "starter_code": PYTHON_GOAL_COMPLETION_STARTER,
            "required_patterns": (),
            "code_blanks": ({
                "blank_key": "sum_output", "expected_concept": "补全求和输出代码：直接输出，或先保存到 total 再输出",
                # Both finite forms require this identifier. Unlike complete
                # literal tails, this concept hint is insensitive to formatting.
                # It is NOT proof of a call/valid goal; sealed AST facts decide.
                "acceptable_patterns": ({"type": "regex", "value": r"\bsum\b"},),
                "is_core": True,
            },),
        },
    })

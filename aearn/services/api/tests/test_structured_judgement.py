"""Unit tests for the shared structured judgement module."""

from app.agents.structured_judgement import (
    FieldPolicy,
    JudgementPolicy,
    StructuredJudgement,
    coerce_structured_judgements,
    normalize_judgements,
)


def _onboarding_policy() -> JudgementPolicy:
    """Example onboarding-like policy for testing."""
    return JudgementPolicy(
        fields=[
            FieldPolicy(name="language", required=True, fallback_question="你想学哪门语言？"),
            FieldPolicy(name="goal_text", required=True, fallback_question="你的学习目标是什么？"),
            FieldPolicy(name="target_level", required=True, fallback_question="你目前的水平如何？"),
            FieldPolicy(
                name="time_budget",
                required=False,
                fallback_question="每天学多久、每周几天？",
                blocks_on=("ambiguous", "unsupported"),
            ),
            FieldPolicy(
                name="focus",
                required=False,
                fallback_question="你想把重点放在哪个方向？",
                blocks_on=("ambiguous", "unsupported"),
            ),
        ],
        default_fallback_question="再补一句你的目标或当前基础。",
    )


def _learning_policy() -> JudgementPolicy:
    """Example non-onboarding policy proving the abstraction is page-agnostic."""
    return JudgementPolicy(
        fields=[
            FieldPolicy(name="answer_correctness", required=True, fallback_question="能再解释一下吗？"),
            FieldPolicy(name="confidence", required=False, blocks_on=("ambiguous",)),
            FieldPolicy(name="misconception", required=False, blocks_on=("ambiguous",)),
        ],
        default_fallback_question="请再试一次。",
    )


class TestNormalizeJudgements:
    def test_all_confirmed_is_ready(self):
        policy = _onboarding_policy()
        values = {"language": "python", "goal_text": "学 Web 开发", "target_level": "beginner"}
        judgements = {
            "language": StructuredJudgement(status="confirmed"),
            "goal_text": StructuredJudgement(status="confirmed"),
            "target_level": StructuredJudgement(status="confirmed"),
        }
        result = normalize_judgements(values, judgements, policy)
        assert result.ready is True
        assert result.cleared_fields == ()
        assert result.blocking_fields == ()
        assert result.clarification_question is None

    def test_ambiguous_required_blocks_and_clears(self):
        policy = _onboarding_policy()
        values = {"language": "python", "goal_text": "学编程", "target_level": "beginner"}
        judgements = {
            "language": StructuredJudgement(status="confirmed"),
            "goal_text": StructuredJudgement(
                status="ambiguous",
                ambiguity_type="goal_unclear",
                clarification_question="你想用 Python 做什么方向？",
            ),
            "target_level": StructuredJudgement(status="confirmed"),
        }
        result = normalize_judgements(values, judgements, policy)
        assert result.ready is False
        assert "goal_text" in result.cleared_fields
        assert "goal_text" in result.blocking_fields
        assert result.clarification_question == "你想用 Python 做什么方向？"

    def test_missing_required_value_blocks(self):
        policy = _onboarding_policy()
        values = {"language": None, "goal_text": "学 Web", "target_level": "beginner"}
        judgements = {
            "language": StructuredJudgement(status="missing", clarification_question="你想学哪门语言？"),
            "goal_text": StructuredJudgement(status="confirmed"),
            "target_level": StructuredJudgement(status="confirmed"),
        }
        result = normalize_judgements(values, judgements, policy)
        assert result.ready is False
        assert "language" in result.blocking_fields

    def test_missing_optional_does_not_block(self):
        policy = _onboarding_policy()
        values = {"language": "python", "goal_text": "学 Web", "target_level": "beginner"}
        judgements = {
            "language": StructuredJudgement(status="confirmed"),
            "goal_text": StructuredJudgement(status="confirmed"),
            "target_level": StructuredJudgement(status="confirmed"),
            "time_budget": StructuredJudgement(status="missing"),
        }
        result = normalize_judgements(values, judgements, policy)
        assert result.ready is True
        assert "time_budget" not in result.blocking_fields

    def test_ambiguous_optional_blocks(self):
        policy = _onboarding_policy()
        values = {
            "language": "python",
            "goal_text": "学 Web",
            "target_level": "beginner",
            "time_budget": "一周几小时",
        }
        judgements = {
            "language": StructuredJudgement(status="confirmed"),
            "goal_text": StructuredJudgement(status="confirmed"),
            "target_level": StructuredJudgement(status="confirmed"),
            "time_budget": StructuredJudgement(
                status="ambiguous",
                ambiguity_type="unit_missing",
                clarification_question="每天学多久、每周几天？",
            ),
        }
        result = normalize_judgements(values, judgements, policy)
        assert result.ready is False
        assert "time_budget" in result.blocking_fields
        assert result.clarification_question == "每天学多久、每周几天？"

    def test_fallback_question_from_policy(self):
        policy = _onboarding_policy()
        values = {"language": None, "goal_text": "学 Web", "target_level": "beginner"}
        judgements = {
            "language": StructuredJudgement(status="missing"),
            "goal_text": StructuredJudgement(status="confirmed"),
            "target_level": StructuredJudgement(status="confirmed"),
        }
        result = normalize_judgements(values, judgements, policy)
        assert result.clarification_question == "你想学哪门语言？"

    def test_unsupported_blocks_required(self):
        policy = _onboarding_policy()
        values = {"language": None, "goal_text": "学 Rust", "target_level": "beginner"}
        judgements = {
            "language": StructuredJudgement(
                status="unsupported",
                clarification_question="目前支持 Python/JS/HTML+CSS/Java/C++。",
            ),
            "goal_text": StructuredJudgement(status="confirmed"),
            "target_level": StructuredJudgement(status="confirmed"),
        }
        result = normalize_judgements(values, judgements, policy)
        assert result.ready is False
        assert "language" in result.blocking_fields

    def test_priority_order_selects_first_blocker_question(self):
        policy = _onboarding_policy()
        values = {"language": None, "goal_text": None, "target_level": "beginner"}
        judgements = {
            "language": StructuredJudgement(
                status="missing", clarification_question="选一门语言"
            ),
            "goal_text": StructuredJudgement(
                status="missing", clarification_question="说说目标"
            ),
            "target_level": StructuredJudgement(status="confirmed"),
        }
        result = normalize_judgements(values, judgements, policy)
        assert result.clarification_question == "选一门语言"

    def test_custom_value_present_fn(self):
        policy = _onboarding_policy()
        values = {"language": "", "goal_text": "学 Web", "target_level": "beginner"}
        judgements = {
            "language": StructuredJudgement(status="confirmed"),
            "goal_text": StructuredJudgement(status="confirmed"),
            "target_level": StructuredJudgement(status="confirmed"),
        }

        def strict_present(name: str, value: object) -> bool:
            if isinstance(value, str):
                return len(value.strip()) >= 2
            return value is not None

        result = normalize_judgements(values, judgements, policy, value_present_fn=strict_present)
        assert result.ready is False
        assert "language" in result.blocking_fields


class TestCoerceStructuredJudgements:
    def test_missing_payload_marks_policy_fields_missing(self):
        policy = _learning_policy()
        judgements = coerce_structured_judgements({}, policy)
        assert judgements["answer_correctness"].status == "missing"
        assert judgements["confidence"].status == "missing"

    def test_invalid_payload_marks_field_unsupported(self):
        policy = _learning_policy()
        judgements = coerce_structured_judgements(
            {"answer_correctness": {"status": "maybe"}},
            policy,
        )
        assert judgements["answer_correctness"].status == "unsupported"

    def test_valid_payload_preserves_clarification_question(self):
        policy = _learning_policy()
        judgements = coerce_structured_judgements(
            {
                "answer_correctness": {
                    "status": "ambiguous",
                    "clarification_question": "你能再解释一下为什么这样？",
                },
            },
            policy,
        )
        assert judgements["answer_correctness"].status == "ambiguous"
        assert judgements["answer_correctness"].clarification_question == "你能再解释一下为什么这样？"


class TestNonOnboardingPolicy:
    """Prove the shared module works for non-onboarding use cases."""

    def test_learning_concept_check_ready(self):
        policy = _learning_policy()
        values = {"answer_correctness": "correct", "confidence": "high"}
        judgements = {
            "answer_correctness": StructuredJudgement(status="confirmed"),
            "confidence": StructuredJudgement(status="confirmed"),
        }
        result = normalize_judgements(values, judgements, policy)
        assert result.ready is True

    def test_learning_concept_check_ambiguous_answer(self):
        policy = _learning_policy()
        values = {"answer_correctness": "partial"}
        judgements = {
            "answer_correctness": StructuredJudgement(
                status="ambiguous",
                clarification_question="你能再解释一下为什么这样？",
            ),
        }
        result = normalize_judgements(values, judgements, policy)
        assert result.ready is False
        assert "answer_correctness" in result.blocking_fields
        assert result.clarification_question == "你能再解释一下为什么这样？"

    def test_learning_missing_optional_no_block(self):
        policy = _learning_policy()
        values = {"answer_correctness": "correct"}
        judgements = {
            "answer_correctness": StructuredJudgement(status="confirmed"),
            "misconception": StructuredJudgement(status="missing"),
        }
        result = normalize_judgements(values, judgements, policy)
        assert result.ready is True

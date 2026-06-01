"""Tests for learner profile persistent memory."""
from __future__ import annotations

import pytest

from app.services.learner_profile import (
    build_profile_summary,
    derive_stable_profile_observations,
    ensure_learner_profile,
    get_learner_profile,
    merge_observations,
)
from app.agents.tools import AgentSideEffects, LearningToolContext, do_update_learner_profile


@pytest.fixture()
def conn():
    from app.core.config import get_settings
    import psycopg
    from psycopg.rows import dict_row

    settings = get_settings()
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        connection.execute("DELETE FROM learner_profiles")
        connection.commit()
        yield connection
        connection.rollback()


@pytest.fixture()
def user_id(conn):
    row = conn.execute(
        "SELECT id FROM users LIMIT 1",
    ).fetchone()
    if row is None:
        row = conn.execute(
            "INSERT INTO users (display_name) VALUES ('test-profile-user') RETURNING id",
        ).fetchone()
        conn.commit()
    return str(row["id"])


class TestLearnerProfile:
    def test_profile_created_on_first_access(self, conn, user_id):
        profile = ensure_learner_profile(conn, user_id)
        conn.commit()
        assert profile["user_id"] == user_id
        assert profile["weak_points"] == []
        assert profile["session_count"] == 0

    def test_get_returns_none_when_not_exists(self, conn):
        result = get_learner_profile(conn, "00000000-0000-0000-0000-000000000000")
        assert result is None

    def test_observations_merge_weak_point(self, conn, user_id):
        observations = [
            {"type": "weak_point", "content": "recursion", "confidence": "confirmed", "session_id": "s1"},
        ]
        profile = merge_observations(conn, user_id, observations)
        conn.commit()
        assert len(profile["weak_points"]) == 1
        assert profile["weak_points"][0]["area"] == "recursion"
        assert profile["weak_points"][0]["evidence_count"] == 1
        assert profile["weak_points"][0]["confidence"] == "confirmed"

    def test_weak_points_accumulate_across_merges(self, conn, user_id):
        merge_observations(conn, user_id, [
            {"type": "weak_point", "content": "recursion", "confidence": "ambiguous", "session_id": "s1"},
        ])
        conn.commit()
        profile = merge_observations(conn, user_id, [
            {"type": "weak_point", "content": "recursion", "confidence": "confirmed", "session_id": "s2"},
        ])
        conn.commit()
        assert len(profile["weak_points"]) == 1
        assert profile["weak_points"][0]["evidence_count"] == 2
        assert profile["weak_points"][0]["confidence"] == "confirmed"

    def test_error_pattern_merge(self, conn, user_id):
        merge_observations(conn, user_id, [
            {"type": "error_pattern", "content": "off_by_one", "confidence": "confirmed", "session_id": "s1"},
        ])
        conn.commit()
        profile = merge_observations(conn, user_id, [
            {"type": "error_pattern", "content": "off_by_one", "confidence": "confirmed", "session_id": "s2"},
            {"type": "error_pattern", "content": "type_coercion", "confidence": "ambiguous", "session_id": "s2"},
        ])
        conn.commit()
        assert len(profile["error_patterns"]) == 2
        off_by_one = next(ep for ep in profile["error_patterns"] if ep["pattern"] == "off_by_one")
        assert off_by_one["frequency"] == 2

    def test_observations_capped_at_50(self, conn, user_id):
        observations = [
            {"type": "weak_point", "content": f"area_{i}", "confidence": "ambiguous", "session_id": f"s{i}"}
            for i in range(60)
        ]
        profile = merge_observations(conn, user_id, observations)
        conn.commit()
        assert len(profile["observations"]) == 50

    def test_learning_preference_merge(self, conn, user_id):
        profile = merge_observations(conn, user_id, [
            {"type": "learning_preference", "content": "", "key": "style", "value": "examples_first", "confidence": "confirmed", "session_id": "s1"},
        ])
        conn.commit()
        assert profile["learning_preferences"]["style"] == "examples_first"

    def test_session_count_increments(self, conn, user_id):
        merge_observations(conn, user_id, [
            {"type": "weak_point", "content": "scope", "confidence": "ambiguous", "session_id": "s1"},
        ])
        conn.commit()
        profile = merge_observations(conn, user_id, [
            {"type": "weak_point", "content": "closures", "confidence": "ambiguous", "session_id": "s2"},
        ])
        conn.commit()
        assert profile["session_count"] == 2


class TestProfileSummary:
    def test_empty_profile_returns_empty_string(self):
        assert build_profile_summary(None) == ""
        assert build_profile_summary({}) == ""

    def test_summary_includes_confirmed_weak_points(self):
        profile = {
            "weak_points": [
                {"area": "recursion", "evidence_count": 3, "confidence": "confirmed"},
                {"area": "scope", "evidence_count": 1, "confidence": "ambiguous"},
            ],
            "error_patterns": [],
            "learning_preferences": {},
            "pace_indicators": {},
            "session_count": 5,
        }
        summary = build_profile_summary(profile)
        assert "recursion" in summary
        assert "scope" not in summary
        assert "累计会话: 5" in summary

    def test_summary_includes_error_patterns(self):
        profile = {
            "weak_points": [],
            "error_patterns": [
                {"pattern": "off_by_one", "frequency": 5, "confidence": "confirmed"},
            ],
            "learning_preferences": {},
            "pace_indicators": {},
            "session_count": 0,
        }
        summary = build_profile_summary(profile)
        assert "off_by_one" in summary
        assert "×5" in summary


class TestStableProfileSignals:
    def test_submit_failure_derives_weak_point_error_pattern_and_pace(self):
        observations = derive_stable_profile_observations(
            attempt={
                "attempt_type": "submit",
                "runtime_status": "runtime_error",
                "test_pass_rate": 0.25,
                "score": 2,
                "fsrs_rating": "Again",
                "error_cause": "missing_base_case",
                "hint_usage_count": 4,
                "error_count": 2,
            },
            knowledge_point={"id": "kp1", "title": "Recursion base cases"},
            session_id="s1",
            source="learn_submit",
        )

        assert {"type": "weak_point", "content": "Recursion base cases", "confidence": "confirmed", "session_id": "s1"} in observations
        assert any(
            item["type"] == "error_pattern" and item["content"] == "missing_base_case"
            for item in observations
        )
        assert any(
            item["type"] == "pace_indicator"
            and item["key"] == "last_attempt_outcome"
            and item["value"] == "needs_repair"
            for item in observations
        )
        assert "submitted_code" not in str(observations)

    def test_review_success_derives_mastery_signal_without_weak_point(self):
        observations = derive_stable_profile_observations(
            attempt={
                "attempt_type": "review_submit",
                "runtime_status": "success",
                "test_pass_rate": 1.0,
                "score": 8,
                "fsrs_rating": "Easy",
                "hint_usage_count": 0,
                "error_count": 0,
            },
            knowledge_point={"id": "kp1", "title": "Closures"},
            session_id="review-s1",
            source="review_submit",
        )

        assert not any(item["type"] == "weak_point" for item in observations)
        assert any(
            item["type"] == "pace_indicator"
            and item["key"] == "mastery_signal"
            and item["value"] == "review_recovered"
            for item in observations
        )
        assert any(
            item["type"] == "pace_indicator"
            and item["key"] == "last_review_rating"
            and item["value"] == "Easy"
            for item in observations
        )

    def test_sensitive_error_cause_falls_back_to_runtime_status(self):
        observations = derive_stable_profile_observations(
            attempt={
                "attempt_type": "submit",
                "runtime_status": "runtime_error",
                "test_pass_rate": 0.0,
                "score": 0,
                "error_cause": "Traceback with api_key=sk-secret",
                "error_count": 1,
            },
            knowledge_point={"title": "Functions"},
            session_id="s1",
            source="learn_submit",
        )

        assert any(
            item["type"] == "error_pattern" and item["content"] == "runtime_error"
            for item in observations
        )
        assert "sk-secret" not in str(observations)


class TestProfileTool:
    def test_do_update_learner_profile_valid(self):
        side_effects = AgentSideEffects()
        ctx = LearningToolContext(session_id="s1", exercise_id=None, current_stage="concept_intro")
        result = do_update_learner_profile(
            side_effects, ctx,
            observation_type="weak_point",
            content="recursion",
            confidence="confirmed",
        )
        assert result["success"] is True
        assert len(side_effects.profile_updates) == 1
        assert side_effects.profile_updates[0]["type"] == "weak_point"

    def test_do_update_learner_profile_invalid_type(self):
        side_effects = AgentSideEffects()
        ctx = LearningToolContext(session_id="s1", exercise_id=None, current_stage="concept_intro")
        result = do_update_learner_profile(
            side_effects, ctx,
            observation_type="invalid_type",
            content="test",
        )
        assert result["success"] is False
        assert "Invalid type" in result["error"]

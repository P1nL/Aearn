"""Learner profile repository — persistent cross-session memory for the teaching agent."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

from psycopg import Connection


MAX_OBSERVATIONS = 50
MAX_WEAK_POINTS = 20
MAX_ERROR_PATTERNS = 20
MAX_SIGNAL_TEXT_LENGTH = 160
REVIEW_FAILURE_RATINGS = {"Again", "Hard"}
REVIEW_SUCCESS_RATINGS = {"Good", "Easy"}
SENSITIVE_SIGNAL_MARKERS = (
    "api_key",
    "auth_token",
    "secret",
    "sk-",
    "stack_trace",
    "traceback",
    "provider payload",
    "hidden_test",
    "solution_reference",
)


def get_learner_profile(conn: Connection[dict[str, object]], user_id: str) -> dict[str, object] | None:
    row = conn.execute(
        "SELECT * FROM learner_profiles WHERE user_id = %s",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return _serialize_profile(row)


def ensure_learner_profile(conn: Connection[dict[str, object]], user_id: str) -> dict[str, object]:
    existing = get_learner_profile(conn, user_id)
    if existing is not None:
        return existing
    row = conn.execute(
        """
        INSERT INTO learner_profiles (user_id)
        VALUES (%s)
        ON CONFLICT (user_id) DO NOTHING
        RETURNING *
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        return get_learner_profile(conn, user_id) or {}
    return _serialize_profile(row)


def merge_observations(
    conn: Connection[dict[str, object]],
    user_id: str,
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Incrementally merge new observations into the learner profile."""
    ensure_learner_profile(conn, user_id)
    profile_row = conn.execute(
        "SELECT * FROM learner_profiles WHERE user_id = %s FOR UPDATE",
        (user_id,),
    ).fetchone()
    if profile_row is None:
        return {}

    weak_points = _as_list(profile_row.get("weak_points"))
    error_patterns = _as_list(profile_row.get("error_patterns"))
    learning_preferences = _as_dict(profile_row.get("learning_preferences"))
    pace_indicators = _as_dict(profile_row.get("pace_indicators"))
    existing_observations = _as_list(profile_row.get("observations"))

    today = date.today().isoformat()

    for obs in observations:
        if not isinstance(obs, Mapping):
            continue
        obs_type = str(obs.get("type", ""))
        content = str(obs.get("content", ""))
        confidence = str(obs.get("confidence", "ambiguous"))
        session_id = str(obs.get("session_id", ""))

        if obs_type == "weak_point" and content:
            weak_points = _merge_weak_point(weak_points, content, confidence, today)
        elif obs_type == "error_pattern" and content:
            error_patterns = _merge_error_pattern(error_patterns, content, confidence, today)
        elif obs_type == "learning_preference":
            key = str(obs.get("key", ""))
            value = str(obs.get("value", ""))
            if key and value:
                learning_preferences = _merge_preference(learning_preferences, key, value, confidence)
        elif obs_type == "pace_indicator":
            key = str(obs.get("key", ""))
            pace_value = obs.get("value")
            if key and pace_value is not None:
                pace_indicators[key] = pace_value

        existing_observations.append({
            "session_id": session_id,
            "timestamp": today,
            "type": obs_type,
            "content": content,
            "confidence": confidence,
        })

    existing_observations = existing_observations[-MAX_OBSERVATIONS:]
    weak_points = weak_points[:MAX_WEAK_POINTS]
    error_patterns = error_patterns[:MAX_ERROR_PATTERNS]

    conn.execute(
        """
        UPDATE learner_profiles
        SET weak_points = %s::jsonb,
            error_patterns = %s::jsonb,
            learning_preferences = %s::jsonb,
            pace_indicators = %s::jsonb,
            observations = %s::jsonb,
            session_count = session_count + 1
        WHERE user_id = %s
        """,
        (
            json.dumps(weak_points, ensure_ascii=False),
            json.dumps(error_patterns, ensure_ascii=False),
            json.dumps(learning_preferences, ensure_ascii=False),
            json.dumps(pace_indicators, ensure_ascii=False),
            json.dumps(existing_observations, ensure_ascii=False),
            user_id,
        ),
    )

    updated = get_learner_profile(conn, user_id)
    return updated or {}


def merge_stable_profile_signals(
    conn: Connection[dict[str, object]],
    user_id: str,
    *,
    attempt: Mapping[str, object],
    knowledge_point: Mapping[str, object] | None = None,
    session_id: str | None = None,
    source: str = "",
) -> dict[str, object]:
    observations = derive_stable_profile_observations(
        attempt=attempt,
        knowledge_point=knowledge_point,
        session_id=session_id,
        source=source,
    )
    if not observations:
        return get_learner_profile(conn, user_id) or ensure_learner_profile(conn, user_id)
    return merge_observations(conn, user_id, observations)


def derive_stable_profile_observations(
    *,
    attempt: Mapping[str, object],
    knowledge_point: Mapping[str, object] | None = None,
    session_id: str | None = None,
    source: str = "",
) -> list[dict[str, object]]:
    """Convert evaluated attempt/review facts into bounded learner profile observations."""
    attempt_type = _signal_text(attempt.get("attempt_type"), max_length=40)
    runtime_status = _signal_text(attempt.get("runtime_status"), max_length=40)
    fsrs_rating = _signal_text(attempt.get("fsrs_rating"), max_length=20)
    test_pass_rate = _as_float(attempt.get("test_pass_rate"), 0.0)
    score = _optional_int(attempt.get("score"))
    hint_usage_count = _as_int(attempt.get("hint_usage_count"), 0)
    error_count = _as_int(attempt.get("error_count"), 0)
    profile_session_id = _signal_text(session_id or attempt.get("session_id"), max_length=80)
    signal_source = _signal_text(source or attempt_type, max_length=80)
    observations: list[dict[str, object]] = []

    weak_point = _knowledge_point_label(knowledge_point)
    if weak_point and _is_weak_attempt_signal(
        runtime_status=runtime_status,
        test_pass_rate=test_pass_rate,
        score=score,
        fsrs_rating=fsrs_rating,
        error_count=error_count,
    ):
        observations.append(_observation(
            "weak_point",
            weak_point,
            session_id=profile_session_id,
            confidence="confirmed",
        ))

    error_pattern = _stable_error_pattern(attempt, runtime_status=runtime_status)
    if error_pattern and (error_count > 0 or runtime_status not in {"", "success"}):
        observations.append(_observation(
            "error_pattern",
            error_pattern,
            session_id=profile_session_id,
            confidence="confirmed" if error_count > 0 else "ambiguous",
        ))

    outcome = _attempt_outcome(
        runtime_status=runtime_status,
        test_pass_rate=test_pass_rate,
        score=score,
        fsrs_rating=fsrs_rating,
        error_count=error_count,
    )
    observations.append(_pace_observation(
        "last_attempt_outcome",
        outcome,
        session_id=profile_session_id,
        source=signal_source,
    ))
    observations.append(_pace_observation(
        "hint_load",
        _hint_load(hint_usage_count),
        session_id=profile_session_id,
        source=signal_source,
    ))
    if fsrs_rating:
        observations.append(_pace_observation(
            "last_review_rating",
            fsrs_rating,
            session_id=profile_session_id,
            source=signal_source,
        ))
    mastery_signal = _mastery_signal(
        attempt_type=attempt_type,
        fsrs_rating=fsrs_rating,
        outcome=outcome,
    )
    if mastery_signal:
        observations.append(_pace_observation(
            "mastery_signal",
            mastery_signal,
            session_id=profile_session_id,
            source=signal_source,
        ))
    return observations


def build_profile_summary(profile: Mapping[str, object] | None) -> str:
    """Build a condensed profile string for injection into the agent system prompt."""
    if not profile:
        return ""

    parts: list[str] = []

    weak_points = profile.get("weak_points")
    if isinstance(weak_points, list) and weak_points:
        confirmed = [wp for wp in weak_points if isinstance(wp, dict) and wp.get("confidence") == "confirmed"]
        if confirmed:
            areas = [str(wp.get("area", "")) for wp in confirmed[:5]]
            parts.append(f"已确认薄弱点: {', '.join(areas)}")

    error_patterns = profile.get("error_patterns")
    if isinstance(error_patterns, list) and error_patterns:
        frequent = sorted(
            [ep for ep in error_patterns if isinstance(ep, dict)],
            key=lambda ep: _as_int(ep.get("frequency"), 0),
            reverse=True,
        )[:3]
        if frequent:
            patterns = [f"{ep.get('pattern')}(×{ep.get('frequency')})" for ep in frequent]
            parts.append(f"常见错误模式: {', '.join(patterns)}")

    prefs = profile.get("learning_preferences")
    if isinstance(prefs, dict) and prefs:
        pref_parts = [f"{k}={v}" for k, v in prefs.items() if v]
        if pref_parts:
            parts.append(f"学习偏好: {', '.join(pref_parts[:4])}")

    pace = profile.get("pace_indicators")
    if isinstance(pace, dict):
        session_count = profile.get("session_count", 0)
        if session_count:
            parts.append(f"累计会话: {session_count}")

    if not parts:
        return ""
    return "【学习者画像】" + " | ".join(parts)


def _merge_weak_point(
    weak_points: list[dict[str, object]],
    area: str,
    confidence: str,
    today: str,
) -> list[dict[str, object]]:
    for wp in weak_points:
        if str(wp.get("area", "")).lower() == area.lower():
            wp["evidence_count"] = _as_int(wp.get("evidence_count"), 0) + 1
            wp["last_seen"] = today
            if confidence == "confirmed":
                wp["confidence"] = "confirmed"
            return weak_points
    weak_points.append({
        "area": area,
        "evidence_count": 1,
        "last_seen": today,
        "confidence": confidence,
    })
    return weak_points


def _merge_error_pattern(
    error_patterns: list[dict[str, object]],
    pattern: str,
    confidence: str,
    today: str,
) -> list[dict[str, object]]:
    for ep in error_patterns:
        if str(ep.get("pattern", "")).lower() == pattern.lower():
            ep["frequency"] = _as_int(ep.get("frequency"), 0) + 1
            ep["last_seen"] = today
            if confidence == "confirmed":
                ep["confidence"] = "confirmed"
            return error_patterns
    error_patterns.append({
        "pattern": pattern,
        "frequency": 1,
        "last_seen": today,
        "confidence": confidence,
    })
    return error_patterns


def _merge_preference(
    prefs: dict[str, object],
    key: str,
    value: str,
    confidence: str,
) -> dict[str, object]:
    existing_confidence = str(prefs.get(f"{key}_confidence", ""))
    if confidence == "confirmed" or existing_confidence != "confirmed":
        prefs[key] = value
        prefs[f"{key}_confidence"] = confidence
    return prefs


def _serialize_profile(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "weak_points": _as_list(row.get("weak_points")),
        "error_patterns": _as_list(row.get("error_patterns")),
        "learning_preferences": _as_dict(row.get("learning_preferences")),
        "pace_indicators": _as_dict(row.get("pace_indicators")),
        "observations": _as_list(row.get("observations")),
        "session_count": _as_int(row.get("session_count"), 0),
    }


def _observation(
    obs_type: str,
    content: str,
    *,
    session_id: str,
    confidence: str,
) -> dict[str, object]:
    return {
        "type": obs_type,
        "content": _signal_text(content),
        "confidence": confidence if confidence in {"confirmed", "ambiguous"} else "ambiguous",
        "session_id": session_id,
    }


def _pace_observation(
    key: str,
    value: str,
    *,
    session_id: str,
    source: str,
) -> dict[str, object]:
    return {
        "type": "pace_indicator",
        "content": f"{key}:{value}",
        "confidence": "confirmed",
        "session_id": session_id,
        "key": _signal_text(key, max_length=80),
        "value": _signal_text(value, max_length=80),
        "source": source,
    }


def _knowledge_point_label(knowledge_point: Mapping[str, object] | None) -> str:
    if not isinstance(knowledge_point, Mapping):
        return ""
    return _signal_text(
        knowledge_point.get("title")
        or knowledge_point.get("knowledge_point_title")
        or knowledge_point.get("name"),
    )


def _is_weak_attempt_signal(
    *,
    runtime_status: str,
    test_pass_rate: float,
    score: int | None,
    fsrs_rating: str,
    error_count: int,
) -> bool:
    if fsrs_rating in REVIEW_FAILURE_RATINGS:
        return True
    if runtime_status and runtime_status not in {"success", "unsupported"}:
        return True
    if error_count > 0:
        return True
    if score is not None and score <= 4:
        return True
    return test_pass_rate < 0.6


def _stable_error_pattern(attempt: Mapping[str, object], *, runtime_status: str) -> str:
    raw_cause = _signal_text(attempt.get("error_cause"), max_length=80)
    if raw_cause and not _has_sensitive_marker(raw_cause):
        return _normalize_pattern(raw_cause)
    if runtime_status and runtime_status != "success":
        return _normalize_pattern(runtime_status)
    return ""


def _attempt_outcome(
    *,
    runtime_status: str,
    test_pass_rate: float,
    score: int | None,
    fsrs_rating: str,
    error_count: int,
) -> str:
    if fsrs_rating in REVIEW_FAILURE_RATINGS:
        return "needs_repair"
    if runtime_status and runtime_status not in {"success", "unsupported"}:
        return "needs_repair"
    if error_count > 0:
        return "needs_repair"
    if fsrs_rating in REVIEW_SUCCESS_RATINGS or (score is not None and score >= 7) or test_pass_rate >= 1.0:
        return "mastered"
    if test_pass_rate >= 0.6:
        return "partial"
    return "needs_repair"


def _hint_load(hint_usage_count: int) -> str:
    if hint_usage_count >= 3:
        return "heavy"
    if hint_usage_count > 0:
        return "used"
    return "none"


def _mastery_signal(*, attempt_type: str, fsrs_rating: str, outcome: str) -> str:
    if attempt_type == "review_submit" and fsrs_rating in REVIEW_SUCCESS_RATINGS:
        return "review_recovered"
    if outcome == "mastered":
        return "mastered"
    return ""


def _signal_text(value: object, max_length: int = MAX_SIGNAL_TEXT_LENGTH) -> str:
    text = str(value or "").strip()
    if _has_sensitive_marker(text):
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length].rstrip()


def _normalize_pattern(value: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in value.strip())
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")[:80]


def _has_sensitive_marker(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in SENSITIVE_SIGNAL_MARKERS)


def _as_list(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        return value
    return []


def _as_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _as_int(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _as_int(value, 0)


def _as_float(value: object, default: float) -> float:
    if isinstance(value, int | float | Decimal):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default

"""Learner profile repository — persistent cross-session memory for the teaching agent."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date

from psycopg import Connection


MAX_OBSERVATIONS = 50
MAX_WEAK_POINTS = 20
MAX_ERROR_PATTERNS = 20


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
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default

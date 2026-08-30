"""Deterministic planning-language intent resolution over the published course catalog."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from psycopg import Connection

from app.services.runners.language_capabilities import LANGUAGE_CAPABILITIES


PLANNING_LANGUAGE_INTENT_POLICY_VERSION = "planning-language-intent-v1"
PLANNING_INTENT_HINT_SCHEMA_VERSION = "planning-intent-hint-v1"

PlanningIntentResolution = Literal[
    "auto_confirm",
    "shortlist",
    "full_catalog",
    "conflict",
    "unsupported",
]
PlanningSelectionScope = Literal[
    "explicit_shortlist",
    "intent_shortlist",
    "conflict_shortlist",
    "full_catalog",
]


@dataclass(frozen=True, slots=True)
class PlanningLanguageIntent:
    policy_version: str
    explicit_language_ids: tuple[str, ...]
    intent_tags: tuple[str, ...]
    candidate_course_ids: tuple[str, ...]
    resolution: PlanningIntentResolution
    reason_code: str

    @property
    def auto_confirm_language_id(self) -> str | None:
        if self.resolution != "auto_confirm" or len(self.explicit_language_ids) != 1:
            return None
        return self.explicit_language_ids[0]

    @property
    def selection_scope(self) -> PlanningSelectionScope:
        if self.resolution == "conflict":
            return "conflict_shortlist"
        if self.explicit_language_ids and self.resolution == "shortlist":
            return "explicit_shortlist"
        if self.intent_tags and self.resolution == "shortlist":
            return "intent_shortlist"
        return "full_catalog"


class PlanningIntentHintError(ValueError):
    pass


_INTENT_ALIASES: Mapping[str, tuple[str, ...]] = {
    "frontend": ("前端", "frontend", "front-end", "front end"),
    "backend": ("后端", "backend", "back-end", "back end", "server-side", "server side", "服务端"),
    "web": ("网页开发", "网站开发", "web development", "web app", "web应用", "web 应用"),
    "data_analysis": ("数据分析", "data analysis", "data analytics"),
    "data_science": ("数据科学", "data science"),
    "database": ("数据库", "database development", "database"),
    "automation": ("自动化", "automation", "脚本开发", "scripting"),
    "general_programming": ("编程基础", "程序设计基础", "programming basics", "learn programming"),
    "mobile": ("移动开发", "移动端开发", "mobile development", "mobile app"),
    "systems": ("系统编程", "底层开发", "systems programming", "low-level programming"),
}
_SHORT_LANGUAGE_ALIASES = frozenset({"py", "js", "ts", "cs", "go"})
_LANGUAGE_CUES = (
    "学习",
    "学",
    "使用",
    "用",
    "写",
    "编程",
    "语言",
    "课程",
    "learn",
    "study",
    "using",
    "use",
    "code",
    "course",
    "programming",
)


class PlanningIntentResolver:
    """Resolve only server-owned languages, intent tags, and active course IDs."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def resolve(
        self,
        learner_text: str,
        *,
        confirmed_language_id: str | None = None,
        model_hint: Mapping[str, object] | None = None,
        enabled: bool = True,
    ) -> PlanningLanguageIntent:
        courses = self._active_courses()
        all_course_ids = tuple(str(row["course_id"]) for row in courses)
        if not enabled:
            return PlanningLanguageIntent(
                policy_version=PLANNING_LANGUAGE_INTENT_POLICY_VERSION,
                explicit_language_ids=(),
                intent_tags=(),
                candidate_course_ids=all_course_ids,
                resolution="full_catalog",
                reason_code="intent_resolution_disabled",
            )

        explicit = detect_explicit_course_languages(learner_text)
        intents = detect_intent_tags(learner_text)
        hinted = self._safe_model_hint_tags(model_hint)
        intents = _ordered_unique((*intents, *hinted))

        courses_by_language: dict[str, list[str]] = {}
        for row in courses:
            courses_by_language.setdefault(str(row["language"]), []).append(str(row["course_id"]))
        explicit_ids = tuple(
            course_id
            for language_id in explicit
            for course_id in courses_by_language.get(language_id, ())
        )
        intent_ids = self._intent_course_ids(intents)

        if confirmed_language_id:
            confirmed = str(confirmed_language_id).strip().lower()
            if explicit and any(language_id != confirmed for language_id in explicit):
                candidates = _ordered_unique((*explicit_ids, *intent_ids))
                return self._result(explicit, intents, candidates or all_course_ids, "conflict", "confirmed_language_conflict")

        if explicit and intents:
            intersection = tuple(course_id for course_id in explicit_ids if course_id in set(intent_ids))
            if intersection:
                if len(explicit) == 1:
                    return self._result(explicit, intents, intersection, "auto_confirm", "explicit_language_intent_match")
                return self._result(explicit, intents, intersection, "shortlist", "explicit_languages_intent_match")
            candidates = _ordered_unique((*explicit_ids, *intent_ids))
            return self._result(explicit, intents, candidates or all_course_ids, "conflict", "explicit_language_intent_conflict")

        if explicit:
            supported = tuple(language_id for language_id in explicit if courses_by_language.get(language_id))
            if len(explicit) == 1 and supported:
                return self._result(explicit, (), explicit_ids, "auto_confirm", "explicit_language_single")
            if explicit_ids:
                code = "explicit_languages_multiple" if len(supported) == len(explicit) else "explicit_languages_partial_unsupported"
                return self._result(explicit, (), explicit_ids, "shortlist", code)
            return self._result(explicit, (), all_course_ids, "unsupported", "explicit_language_unsupported")

        if intents:
            if intent_ids:
                return self._result((), intents, intent_ids, "shortlist", "intent_tag_match")
            return self._result((), intents, all_course_ids, "full_catalog", "intent_tag_no_active_course")

        return self._result((), (), all_course_ids, "full_catalog", "no_intent_signal")

    def resolve_for_run(
        self,
        *,
        user_id: str,
        run_id: str,
        enabled: bool = True,
        model_hint: Mapping[str, object] | None = None,
    ) -> PlanningLanguageIntent:
        row = self._conn.execute(
            """
            SELECT messages.content
            FROM tutor_runs AS runs
            JOIN tutor_run_input_events AS inputs
              ON inputs.run_id = runs.id AND inputs.input_revision = runs.input_revision
            JOIN tutor_messages AS messages
              ON messages.id = inputs.message_id AND messages.conversation_id = runs.conversation_id
            WHERE runs.id = %s AND runs.user_id = %s
            """,
            (run_id, user_id),
        ).fetchone()
        confirmed = self._conn.execute(
            """
            SELECT facts.value_json
            FROM tutor_planning_intake_facts AS facts
            JOIN tutor_learning_plan_sessions AS sessions ON sessions.id = facts.session_id
            JOIN tutor_runs AS runs
              ON runs.conversation_id = sessions.conversation_id AND runs.user_id = sessions.user_id
            WHERE runs.id = %s AND runs.user_id = %s
              AND facts.field_key = 'language_id' AND facts.state = 'confirmed'
              AND NOT EXISTS (
                SELECT 1 FROM tutor_planning_intake_facts AS successor
                WHERE successor.supersedes_fact_id = facts.id
              )
            ORDER BY facts.revision DESC
            LIMIT 1
            """,
            (run_id, user_id),
        ).fetchone()
        return self.resolve(
            str(row["content"] if row is not None else ""),
            confirmed_language_id=(str(confirmed["value_json"]) if confirmed is not None else None),
            model_hint=model_hint,
            enabled=enabled,
        )

    def _active_courses(self) -> list[dict[str, object]]:
        rows = self._conn.execute(
            """
            SELECT id::text AS course_id, language, title, level
            FROM language_courses
            WHERE archived_at IS NULL
            ORDER BY language, level, title, id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def _intent_course_ids(self, intent_tags: Sequence[str]) -> tuple[str, ...]:
        if not intent_tags:
            return ()
        rows = self._conn.execute(
            """
            SELECT tags.course_id::text AS course_id,
                   max(tags.relevance_rank)::int AS relevance_rank,
                   bool_or(tags.is_primary) AS is_primary,
                   courses.language,
                   courses.title
            FROM language_course_intent_tags AS tags
            JOIN tutor_learning_intents AS intents
              ON intents.intent_key = tags.intent_key AND intents.state = 'active'
            JOIN language_courses AS courses
              ON courses.id = tags.course_id AND courses.archived_at IS NULL
            WHERE tags.intent_key = ANY(%s)
            GROUP BY tags.course_id, courses.language, courses.title
            ORDER BY max(tags.relevance_rank) DESC, bool_or(tags.is_primary) DESC,
                     courses.language, courses.title, tags.course_id
            """,
            (list(intent_tags),),
        ).fetchall()
        return tuple(str(row["course_id"]) for row in rows)

    def _safe_model_hint_tags(self, payload: Mapping[str, object] | None) -> tuple[str, ...]:
        if payload is None:
            return ()
        try:
            return validate_closed_intent_hint(self._conn, payload)
        except PlanningIntentHintError:
            return ()

    @staticmethod
    def _result(
        explicit: Sequence[str],
        intents: Sequence[str],
        candidates: Sequence[str],
        resolution: PlanningIntentResolution,
        reason_code: str,
    ) -> PlanningLanguageIntent:
        return PlanningLanguageIntent(
            policy_version=PLANNING_LANGUAGE_INTENT_POLICY_VERSION,
            explicit_language_ids=tuple(explicit),
            intent_tags=tuple(intents),
            candidate_course_ids=tuple(candidates),
            resolution=resolution,
            reason_code=reason_code,
        )


def validate_closed_intent_hint(
    conn: Connection[dict[str, object]],
    payload: Mapping[str, object],
) -> tuple[str, ...]:
    if set(payload) != {"schema_version", "intent_tags"}:
        raise PlanningIntentHintError("planning intent hint fields are invalid")
    if payload.get("schema_version") != PLANNING_INTENT_HINT_SCHEMA_VERSION:
        raise PlanningIntentHintError("planning intent hint schema is invalid")
    raw_tags = payload.get("intent_tags")
    if not isinstance(raw_tags, list) or len(raw_tags) > 4 or any(not isinstance(item, str) for item in raw_tags):
        raise PlanningIntentHintError("planning intent hint tags are invalid")
    tags = _ordered_unique(str(item).strip() for item in raw_tags if str(item).strip())
    if len(tags) != len(raw_tags):
        raise PlanningIntentHintError("planning intent hint tags must be unique and non-empty")
    rows = conn.execute(
        "SELECT intent_key FROM tutor_learning_intents WHERE state = 'active' AND intent_key = ANY(%s)",
        (list(tags),),
    ).fetchall()
    known = {str(row["intent_key"]) for row in rows}
    if set(tags) != known:
        raise PlanningIntentHintError("planning intent hint contains an unknown or inactive tag")
    return tags


def detect_explicit_course_languages(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    matches: list[tuple[int, str]] = []
    for capability in LANGUAGE_CAPABILITIES.values():
        public_language = capability.current_public_course_language
        if public_language is None:
            public_language = capability.language_id
        aliases = _ordered_unique(
            (
                capability.language_id,
                capability.display_name,
                *capability.aliases,
                *({"csharp": ("c sharp", "c-sharp"), "javascript": ("java script",)}.get(capability.language_id, ())),
            )
        )
        for alias in aliases:
            for position in _alias_positions(normalized, alias):
                matches.append((position, public_language))
    matches.sort(key=lambda item: item[0])
    return _ordered_unique(language_id for _position, language_id in matches)


def detect_intent_tags(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", str(text or "")).casefold()
    matches: list[tuple[int, str]] = []
    for intent_key, aliases in _INTENT_ALIASES.items():
        positions = [position for alias in aliases if (position := _phrase_position(normalized, alias.casefold())) >= 0]
        if positions:
            matches.append((min(positions), intent_key))
    matches.sort(key=lambda item: item[0])
    return tuple(intent_key for _position, intent_key in matches)


def _alias_positions(text: str, alias: str) -> tuple[int, ...]:
    alias = unicodedata.normalize("NFKC", alias)
    escaped = re.escape(alias)
    if alias and all(character.isalnum() or character in {"_", "-"} for character in alias):
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", re.IGNORECASE)
    else:
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])", re.IGNORECASE)
    positions: list[int] = []
    for match in pattern.finditer(text):
        normalized_alias = alias.casefold().replace("-", "")
        if normalized_alias in _SHORT_LANGUAGE_ALIASES and not _short_alias_is_explicit(text, match.start(), match.end(), alias):
            continue
        positions.append(match.start())
    return tuple(positions)


def _short_alias_is_explicit(text: str, start: int, end: int, alias: str) -> bool:
    token = text[start:end]
    if alias.casefold() == "go" and token == "Go":
        return True
    if len(token) <= 3 and any(character.isalpha() for character in token) and token.isupper():
        return True
    context = text[max(0, start - 20): min(len(text), end + 20)].casefold()
    return any(cue in context for cue in _LANGUAGE_CUES)


def _phrase_position(text: str, phrase: str) -> int:
    if not phrase:
        return -1
    if all(character.isascii() and (character.isalnum() or character in {"-", " "}) for character in phrase):
        match = re.search(rf"(?<![A-Za-z0-9_]){re.escape(phrase)}(?![A-Za-z0-9_])", text)
        return match.start() if match is not None else -1
    return text.find(phrase)


def _ordered_unique(values: Iterable[object]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return tuple(result)

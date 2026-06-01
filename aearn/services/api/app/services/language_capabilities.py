from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CapabilityState = Literal["full", "partial", "planned", "unsupported"]
GroundingState = Literal["official", "trusted", "internal_only", "planned", "unsupported"]
ExerciseGenerationState = Literal["executable", "static_review", "planned", "unsupported"]
ExecutionMode = Literal[
    "browser_preview",
    "python_stdout_test",
    "node_later",
    "sql_later",
    "compiled_later",
    "none",
]
TestSupport = Literal["visible_hidden", "visible_only", "static_review_only", "none"]
StaticAnalysisSupport = Literal["syntax_only", "lint_later", "planned", "none"]
ReviewFeedbackSupport = Literal["full", "static_only", "planned", "unsupported"]
PresentationMode = Literal["browser_preview", "stdout", "citation_only", "static_feedback", "none"]
RunnerKey = Literal["browser", "python", "node", "sql", "compiled", "none"]
SourceTrustPolicy = Literal["official", "trusted_de_facto", "internal"]


@dataclass(frozen=True, slots=True)
class LanguageCapability:
    language_id: str
    display_name: str
    aliases: tuple[str, ...]
    current_public_course_language: str | None
    capability_state: CapabilityState
    lesson_generation: CapabilityState
    grounding: GroundingState
    exercise_generation: ExerciseGenerationState
    execution: ExecutionMode
    tests: TestSupport
    static_analysis: StaticAnalysisSupport
    review_feedback: ReviewFeedbackSupport
    presentation: PresentationMode
    ux_disclosure: str
    runner_key: RunnerKey
    source_trust_policy: SourceTrustPolicy
    enabled_for_public_selection: bool
    sandbox_boundary: str | None = None

    @property
    def supports_execution(self) -> bool:
        return self.execution in {"browser_preview", "python_stdout_test"}

    @property
    def supports_tests(self) -> bool:
        return self.tests in {"visible_hidden", "visible_only"}


LANGUAGE_CAPABILITIES: dict[str, LanguageCapability] = {
    "python": LanguageCapability(
        language_id="python",
        display_name="Python",
        aliases=("py", "python3"),
        current_public_course_language="python",
        capability_state="full",
        lesson_generation="full",
        grounding="planned",
        exercise_generation="executable",
        execution="python_stdout_test",
        tests="visible_hidden",
        static_analysis="syntax_only",
        review_feedback="full",
        presentation="stdout",
        ux_disclosure="Python can run stdout and visible-test exercises, but the subprocess sandbox is not OS-container isolation.",
        runner_key="python",
        source_trust_policy="official",
        enabled_for_public_selection=True,
        sandbox_boundary="subprocess_restricted_not_container",
    ),
    "javascript": LanguageCapability(
        language_id="javascript",
        display_name="JavaScript",
        aliases=("js", "ecmascript"),
        current_public_course_language="javascript",
        capability_state="full",
        lesson_generation="full",
        grounding="planned",
        exercise_generation="executable",
        execution="browser_preview",
        tests="visible_hidden",
        static_analysis="syntax_only",
        review_feedback="full",
        presentation="browser_preview",
        ux_disclosure="JavaScript can use browser preview and DOM-style assertions in the current course runtime.",
        runner_key="browser",
        source_trust_policy="official",
        enabled_for_public_selection=True,
    ),
    "typescript": LanguageCapability(
        language_id="typescript",
        display_name="TypeScript",
        aliases=("ts",),
        current_public_course_language=None,
        capability_state="planned",
        lesson_generation="planned",
        grounding="planned",
        exercise_generation="planned",
        execution="node_later",
        tests="none",
        static_analysis="planned",
        review_feedback="planned",
        presentation="static_feedback",
        ux_disclosure="TypeScript execution is planned for a later Node/TypeScript runner and is not runnable yet.",
        runner_key="node",
        source_trust_policy="official",
        enabled_for_public_selection=False,
    ),
    "java": LanguageCapability(
        language_id="java",
        display_name="Java",
        aliases=(),
        current_public_course_language="java",
        capability_state="partial",
        lesson_generation="partial",
        grounding="planned",
        exercise_generation="static_review",
        execution="compiled_later",
        tests="static_review_only",
        static_analysis="planned",
        review_feedback="static_only",
        presentation="static_feedback",
        ux_disclosure="Java compile-and-run sandbox support is planned later; current exercises must disclose static review limits.",
        runner_key="compiled",
        source_trust_policy="official",
        enabled_for_public_selection=True,
    ),
    "go": LanguageCapability(
        language_id="go",
        display_name="Go",
        aliases=("golang",),
        current_public_course_language=None,
        capability_state="planned",
        lesson_generation="planned",
        grounding="planned",
        exercise_generation="planned",
        execution="compiled_later",
        tests="none",
        static_analysis="planned",
        review_feedback="planned",
        presentation="static_feedback",
        ux_disclosure="Go execution is planned for a later compiled-language runner and is not runnable yet.",
        runner_key="compiled",
        source_trust_policy="official",
        enabled_for_public_selection=False,
    ),
    "csharp": LanguageCapability(
        language_id="csharp",
        display_name="C#",
        aliases=("c#", "cs"),
        current_public_course_language=None,
        capability_state="planned",
        lesson_generation="planned",
        grounding="planned",
        exercise_generation="planned",
        execution="compiled_later",
        tests="none",
        static_analysis="planned",
        review_feedback="planned",
        presentation="static_feedback",
        ux_disclosure="C# execution is planned for a later compiled-language runner and is not runnable yet.",
        runner_key="compiled",
        source_trust_policy="official",
        enabled_for_public_selection=False,
    ),
    "rust": LanguageCapability(
        language_id="rust",
        display_name="Rust",
        aliases=("rs",),
        current_public_course_language=None,
        capability_state="planned",
        lesson_generation="planned",
        grounding="planned",
        exercise_generation="planned",
        execution="compiled_later",
        tests="none",
        static_analysis="planned",
        review_feedback="planned",
        presentation="static_feedback",
        ux_disclosure="Rust execution is planned for a later compiled-language runner and is not runnable yet.",
        runner_key="compiled",
        source_trust_policy="official",
        enabled_for_public_selection=False,
    ),
    "cpp": LanguageCapability(
        language_id="cpp",
        display_name="C++",
        aliases=("c++",),
        current_public_course_language="cpp",
        capability_state="partial",
        lesson_generation="partial",
        grounding="trusted",
        exercise_generation="static_review",
        execution="compiled_later",
        tests="static_review_only",
        static_analysis="planned",
        review_feedback="static_only",
        presentation="static_feedback",
        ux_disclosure="C++ compile-and-run sandbox support is planned later; cppreference may be used as trusted documentation grounding.",
        runner_key="compiled",
        source_trust_policy="trusted_de_facto",
        enabled_for_public_selection=True,
    ),
    "sql": LanguageCapability(
        language_id="sql",
        display_name="SQL",
        aliases=(),
        current_public_course_language=None,
        capability_state="planned",
        lesson_generation="planned",
        grounding="planned",
        exercise_generation="planned",
        execution="sql_later",
        tests="none",
        static_analysis="planned",
        review_feedback="planned",
        presentation="static_feedback",
        ux_disclosure="SQL execution requires an isolated query runner and is not runnable yet.",
        runner_key="sql",
        source_trust_policy="trusted_de_facto",
        enabled_for_public_selection=False,
    ),
    "html": LanguageCapability(
        language_id="html",
        display_name="HTML",
        aliases=(),
        current_public_course_language="html_css",
        capability_state="full",
        lesson_generation="full",
        grounding="planned",
        exercise_generation="executable",
        execution="browser_preview",
        tests="visible_hidden",
        static_analysis="syntax_only",
        review_feedback="full",
        presentation="browser_preview",
        ux_disclosure="HTML runs through the combined HTML/CSS browser preview course boundary.",
        runner_key="browser",
        source_trust_policy="official",
        enabled_for_public_selection=True,
    ),
    "css": LanguageCapability(
        language_id="css",
        display_name="CSS",
        aliases=(),
        current_public_course_language="html_css",
        capability_state="full",
        lesson_generation="full",
        grounding="planned",
        exercise_generation="executable",
        execution="browser_preview",
        tests="visible_hidden",
        static_analysis="syntax_only",
        review_feedback="full",
        presentation="browser_preview",
        ux_disclosure="CSS runs through the combined HTML/CSS browser preview course boundary.",
        runner_key="browser",
        source_trust_policy="official",
        enabled_for_public_selection=True,
    ),
}


PUBLIC_COURSE_LANGUAGE_MAP: dict[str, tuple[str, ...]] = {
    "javascript": ("javascript",),
    "python": ("python",),
    "java": ("java",),
    "cpp": ("cpp",),
    "html_css": ("html", "css"),
}


def get_language_capability(language_id_or_alias: str) -> LanguageCapability | None:
    normalized = _normalize_language_id(language_id_or_alias)
    if normalized in LANGUAGE_CAPABILITIES:
        return LANGUAGE_CAPABILITIES[normalized]
    for capability in LANGUAGE_CAPABILITIES.values():
        if normalized in {_normalize_language_id(alias) for alias in capability.aliases}:
            return capability
    return None


def require_language_capability(language_id_or_alias: str) -> LanguageCapability:
    capability = get_language_capability(language_id_or_alias)
    if capability is None:
        raise KeyError(f"Unknown language capability: {language_id_or_alias}")
    return capability


def capabilities_for_public_course_language(public_language: str) -> tuple[LanguageCapability, ...]:
    return tuple(LANGUAGE_CAPABILITIES[language_id] for language_id in PUBLIC_COURSE_LANGUAGE_MAP.get(public_language, ()))


def all_language_capabilities() -> tuple[LanguageCapability, ...]:
    return tuple(LANGUAGE_CAPABILITIES[language_id] for language_id in sorted(LANGUAGE_CAPABILITIES))


def public_course_language_ids() -> tuple[str, ...]:
    return tuple(PUBLIC_COURSE_LANGUAGE_MAP)


def _normalize_language_id(value: str) -> str:
    return value.strip().lower().replace("-", "").replace("_", "")

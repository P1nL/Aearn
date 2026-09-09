from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from app.services.runners.language_capabilities import all_language_capabilities, get_language_capability


SourceTrustTier = Literal["official", "trusted_de_facto", "internal"]
SourceSeedPolicy = Literal["seed_urls_only"]
SourceContentType = Literal["tutorial", "reference", "spec", "platform_docs", "vendor_docs"]
SourceVersionKind = Literal["fixed", "rolling"]


@dataclass(frozen=True, slots=True)
class GroundingSource:
    source_id: str
    language_id: str
    display_name: str
    provider: str
    trust_tier: SourceTrustTier
    seed_policy: SourceSeedPolicy
    content_type: SourceContentType
    allowlisted_domains: tuple[str, ...]
    seed_urls: tuple[str, ...]
    topic_tags: tuple[str, ...]
    source_version_label: str
    source_version_kind: SourceVersionKind
    notes: str = ""


GROUNDING_SOURCES: tuple[GroundingSource, ...] = (
    GroundingSource(
        source_id="python-tutorial",
        language_id="python",
        display_name="Python Tutorial",
        provider="Python Software Foundation",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="tutorial",
        allowlisted_domains=("docs.python.org",),
        seed_urls=(
            "https://docs.python.org/3/tutorial/index.html",
            "https://docs.python.org/3/tutorial/introduction.html",
            "https://docs.python.org/3/tutorial/controlflow.html",
        ),
        topic_tags=("basics", "control-flow", "functions", "modules", "io", "errors", "classes"),
        source_version_label="python-3",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="python-library-reference",
        language_id="python",
        display_name="Python Standard Library",
        provider="Python Software Foundation",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="reference",
        allowlisted_domains=("docs.python.org",),
        seed_urls=("https://docs.python.org/3/library/index.html",),
        topic_tags=("stdlib", "data-types", "exceptions", "text", "collections"),
        source_version_label="python-3",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="mdn-javascript-guide",
        language_id="javascript",
        display_name="MDN JavaScript Guide",
        provider="MDN Web Docs",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="tutorial",
        allowlisted_domains=("developer.mozilla.org",),
        seed_urls=("https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide",),
        topic_tags=("basics", "control-flow", "functions", "objects", "async", "modules"),
        source_version_label="mdn-current",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="mdn-javascript-reference",
        language_id="javascript",
        display_name="MDN JavaScript Reference",
        provider="MDN Web Docs",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="reference",
        allowlisted_domains=("developer.mozilla.org",),
        seed_urls=("https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference",),
        topic_tags=("syntax", "standard-objects", "operators", "statements"),
        source_version_label="mdn-current",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="typescript-handbook",
        language_id="typescript",
        display_name="TypeScript Handbook",
        provider="Microsoft TypeScript",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="tutorial",
        allowlisted_domains=("www.typescriptlang.org",),
        seed_urls=("https://www.typescriptlang.org/docs/handbook/intro.html",),
        topic_tags=("types", "functions", "objects", "classes", "modules", "narrowing"),
        source_version_label="typescript-current",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="dev-java-learn",
        language_id="java",
        display_name="dev.java Learn",
        provider="Oracle Java",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="tutorial",
        allowlisted_domains=("dev.java",),
        seed_urls=("https://dev.java/learn/",),
        topic_tags=("basics", "classes", "collections", "concurrency", "tools"),
        source_version_label="java-current",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="oracle-java-api",
        language_id="java",
        display_name="Java SE API Documentation",
        provider="Oracle Java",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="reference",
        allowlisted_domains=("docs.oracle.com",),
        seed_urls=("https://docs.oracle.com/en/java/javase/21/docs/api/index.html",),
        topic_tags=("api", "stdlib", "collections", "io", "exceptions"),
        source_version_label="java-se-21",
        source_version_kind="fixed",
    ),
    GroundingSource(
        source_id="go-docs",
        language_id="go",
        display_name="Go Documentation",
        provider="Go Project",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="tutorial",
        allowlisted_domains=("go.dev",),
        seed_urls=("https://go.dev/doc/",),
        topic_tags=("basics", "modules", "effective-go", "testing", "tools"),
        source_version_label="go-current",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="go-tour",
        language_id="go",
        display_name="A Tour of Go",
        provider="Go Project",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="tutorial",
        allowlisted_domains=("go.dev",),
        seed_urls=("https://go.dev/tour/list",),
        topic_tags=("basics", "methods", "interfaces", "concurrency"),
        source_version_label="go-current",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="microsoft-csharp-guide",
        language_id="csharp",
        display_name="C# Guide",
        provider="Microsoft Learn",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="tutorial",
        allowlisted_domains=("learn.microsoft.com",),
        seed_urls=(
            "https://learn.microsoft.com/en-us/dotnet/csharp/",
            "https://learn.microsoft.com/en-us/dotnet/csharp/tour-of-csharp/",
        ),
        topic_tags=("basics", "types", "classes", "linq", "async", "dotnet"),
        source_version_label="dotnet-current",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="rust-book",
        language_id="rust",
        display_name="The Rust Programming Language",
        provider="Rust Project",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="tutorial",
        allowlisted_domains=("doc.rust-lang.org",),
        seed_urls=("https://doc.rust-lang.org/book/",),
        topic_tags=("ownership", "borrowing", "lifetimes", "structs", "enums", "error-handling"),
        source_version_label="rust-current",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="rust-std",
        language_id="rust",
        display_name="Rust Standard Library",
        provider="Rust Project",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="reference",
        allowlisted_domains=("doc.rust-lang.org",),
        seed_urls=("https://doc.rust-lang.org/std/",),
        topic_tags=("stdlib", "collections", "result", "option", "iterators"),
        source_version_label="rust-current",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="cppreference-cpp",
        language_id="cpp",
        display_name="cppreference C++",
        provider="cppreference",
        trust_tier="trusted_de_facto",
        seed_policy="seed_urls_only",
        content_type="reference",
        allowlisted_domains=("en.cppreference.com",),
        seed_urls=("https://en.cppreference.com/w/cpp",),
        topic_tags=("language", "stdlib", "containers", "algorithms", "templates", "memory"),
        notes="C++ has no single official beginner documentation source; cppreference is the trusted de facto reference.",
        source_version_label="cppreference-current",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="postgresql-sql-docs",
        language_id="sql",
        display_name="PostgreSQL SQL Documentation",
        provider="PostgreSQL Global Development Group",
        trust_tier="trusted_de_facto",
        seed_policy="seed_urls_only",
        content_type="vendor_docs",
        allowlisted_domains=("www.postgresql.org",),
        seed_urls=("https://www.postgresql.org/docs/current/tutorial.html", "https://www.postgresql.org/docs/current/sql.html"),
        topic_tags=("queries", "joins", "aggregation", "ddl", "transactions", "postgresql"),
        notes="SQL grounding uses trusted vendor documentation because SQL has dialect-specific behavior.",
        source_version_label="postgresql-current",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="mdn-html",
        language_id="html",
        display_name="MDN HTML",
        provider="MDN Web Docs",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="tutorial",
        allowlisted_domains=("developer.mozilla.org",),
        seed_urls=("https://developer.mozilla.org/en-US/docs/Web/HTML",),
        topic_tags=("semantics", "forms", "accessibility", "document-structure"),
        source_version_label="mdn-current",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="whatwg-html-spec",
        language_id="html",
        display_name="HTML Living Standard",
        provider="WHATWG",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="spec",
        allowlisted_domains=("html.spec.whatwg.org",),
        seed_urls=("https://html.spec.whatwg.org/multipage/",),
        topic_tags=("spec", "elements", "forms", "dom", "semantics"),
        source_version_label="living-standard",
        source_version_kind="rolling",
    ),
    GroundingSource(
        source_id="mdn-css",
        language_id="css",
        display_name="MDN CSS",
        provider="MDN Web Docs",
        trust_tier="official",
        seed_policy="seed_urls_only",
        content_type="tutorial",
        allowlisted_domains=("developer.mozilla.org",),
        seed_urls=("https://developer.mozilla.org/en-US/docs/Web/CSS",),
        topic_tags=("selectors", "cascade", "box-model", "layout", "responsive", "animations"),
        source_version_label="mdn-current",
        source_version_kind="rolling",
    ),
)


def all_grounding_sources() -> tuple[GroundingSource, ...]:
    return GROUNDING_SOURCES


def sources_for_language(language_id_or_alias: str) -> tuple[GroundingSource, ...]:
    capability = get_language_capability(language_id_or_alias)
    if capability is None:
        return ()
    return tuple(source for source in GROUNDING_SOURCES if source.language_id == capability.language_id)


def get_grounding_source(source_id: str) -> GroundingSource | None:
    normalized_source_id = source_id.strip()
    for source in GROUNDING_SOURCES:
        if source.source_id == normalized_source_id:
            return source
    return None


def allowlisted_domains_for_source(source_id: str) -> tuple[str, ...]:
    source = get_grounding_source(source_id)
    if source is None:
        return ()
    return source.allowlisted_domains


def seed_urls_for_language(language_id_or_alias: str) -> tuple[str, ...]:
    return tuple(seed_url for source in sources_for_language(language_id_or_alias) for seed_url in source.seed_urls)


def validate_grounding_source_registry() -> tuple[str, ...]:
    errors: list[str] = []
    known_capabilities = {capability.language_id: capability for capability in all_language_capabilities()}
    seen_source_ids: set[str] = set()
    covered_language_ids: set[str] = set()

    for source in GROUNDING_SOURCES:
        if source.source_id in seen_source_ids:
            errors.append(f"Duplicate grounding source id: {source.source_id}")
        seen_source_ids.add(source.source_id)

        capability = known_capabilities.get(source.language_id)
        if capability is None:
            errors.append(f"Unknown language id for grounding source {source.source_id}: {source.language_id}")
        else:
            covered_language_ids.add(source.language_id)

        if not source.allowlisted_domains:
            errors.append(f"Grounding source {source.source_id} has no allowlisted domains")
        if not source.seed_urls:
            errors.append(f"Grounding source {source.source_id} has no seed URLs")
        if not source.source_version_label.strip():
            errors.append(f"Grounding source {source.source_id} has no source version label")
        if source.source_version_kind not in {"fixed", "rolling"}:
            errors.append(f"Grounding source {source.source_id} has an invalid source version kind")
        for seed_url in source.seed_urls:
            if not _seed_url_is_allowlisted(seed_url, source.allowlisted_domains):
                errors.append(f"Grounding source {source.source_id} seed URL is not allowlisted: {seed_url}")

    missing_language_ids = set(known_capabilities) - covered_language_ids
    for language_id in sorted(missing_language_ids):
        errors.append(f"Missing grounding source for language: {language_id}")

    for language_id, capability in sorted(known_capabilities.items()):
        sources = sources_for_language(language_id)
        if sources and not any(_trust_tier_matches_policy(source.trust_tier, capability.source_trust_policy) for source in sources):
            errors.append(
                f"No grounding source for {language_id} matches trust policy {capability.source_trust_policy}",
            )

    return tuple(errors)


def _seed_url_is_allowlisted(seed_url: str, allowlisted_domains: tuple[str, ...]) -> bool:
    parsed_url = urlparse(seed_url)
    if parsed_url.scheme not in {"http", "https"}:
        return False
    hostname = (parsed_url.hostname or "").lower()
    return any(_hostname_matches_domain(hostname, domain) for domain in allowlisted_domains)


def _hostname_matches_domain(hostname: str, domain: str) -> bool:
    normalized_domain = domain.lower()
    return hostname == normalized_domain or hostname.endswith(f".{normalized_domain}")


def _trust_tier_matches_policy(trust_tier: SourceTrustTier, policy: str) -> bool:
    if policy == "official":
        return trust_tier == "official"
    if policy == "trusted_de_facto":
        return trust_tier in {"official", "trusted_de_facto"}
    if policy == "internal":
        return trust_tier == "internal"
    return False

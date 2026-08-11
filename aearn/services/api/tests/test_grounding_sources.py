from __future__ import annotations

from app.services.grounding.grounding_sources import (
    all_grounding_sources,
    allowlisted_domains_for_source,
    get_grounding_source,
    seed_urls_for_language,
    sources_for_language,
    validate_grounding_source_registry,
)
from app.services.runners.language_capabilities import all_language_capabilities, require_language_capability


def test_grounding_sources_cover_all_language_capabilities() -> None:
    covered_language_ids = {source.language_id for source in all_grounding_sources()}
    expected_language_ids = {capability.language_id for capability in all_language_capabilities()}

    assert covered_language_ids == expected_language_ids


def test_source_ids_are_unique_and_registry_validates_cleanly() -> None:
    sources = all_grounding_sources()
    source_ids = [source.source_id for source in sources]

    assert len(source_ids) == len(set(source_ids))
    assert validate_grounding_source_registry() == ()
    assert all(source.source_version_label for source in sources)
    assert {source.source_version_kind for source in sources} <= {"fixed", "rolling"}


def test_helpers_return_tuple_contracts_and_support_alias_lookup() -> None:
    javascript_sources = sources_for_language("JS")
    javascript_seed_urls = seed_urls_for_language("javascript")

    assert isinstance(javascript_sources, tuple)
    assert isinstance(javascript_seed_urls, tuple)
    assert {source.language_id for source in javascript_sources} == {"javascript"}
    assert any("developer.mozilla.org" in url for url in javascript_seed_urls)
    assert sources_for_language("unknown-language") == ()
    assert seed_urls_for_language("unknown-language") == ()


def test_seed_urls_stay_under_allowlisted_domains() -> None:
    for source in all_grounding_sources():
        domains = allowlisted_domains_for_source(source.source_id)

        assert domains == source.allowlisted_domains
        for seed_url in source.seed_urls:
            assert any(domain in seed_url for domain in domains)


def test_cpp_uses_trusted_de_facto_source_with_disclosure() -> None:
    cpp_sources = sources_for_language("c++")
    cppreference = get_grounding_source("cppreference-cpp")

    assert cppreference in cpp_sources
    assert cppreference is not None
    assert cppreference.trust_tier == "trusted_de_facto"
    assert "no single official" in cppreference.notes


def test_grounding_sources_preserve_current_public_language_capabilities() -> None:
    expected_capabilities = {
        "typescript": (True, True),
        "go": (True, True),
        "csharp": (True, True),
        "rust": (False, False),
        "sql": (True, True),
    }

    for language_id, (enabled_for_public_selection, supports_execution) in expected_capabilities.items():
        capability = require_language_capability(language_id)

        assert sources_for_language(language_id)
        assert capability.enabled_for_public_selection is enabled_for_public_selection
        assert capability.supports_execution is supports_execution

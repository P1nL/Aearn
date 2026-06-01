# Grounding source registry

## Goal

Define mainstream language source providers, allowlisted domains, seed URL policies, source trust tiers, and language/topic metadata.

## Confirmed Facts

- `aearn/services/api/app/services/language_capabilities.py` is the current source of truth for mainstream language ids, aliases, public-course mappings, and source trust policy.
- The parent `language-knowledge-grounding` task requires coverage for Python, JavaScript, TypeScript, Java, Go, C#, Rust, C++, SQL, HTML, and CSS.
- Existing `teaching_chunks` indexing is internal lesson-content RAG and source-note indexing only; this task must not implement external fetching, cleaning, chunking, retrieval ranking, or citation integration.
- Existing plan-generation web tools can search/fetch doc TOCs during dynamic plan generation, but the grounding registry must not give runtime agents arbitrary web browsing.
- C++ does not have a single official beginner documentation source; `cppreference` is acceptable as a trusted/de facto source and must be marked with a non-official trust tier.
- TypeScript, Go, C#, Rust, and SQL remain planned/unsupported for execution. Documentation grounding must not imply runnable exercises or public selection.

## Requirements

- Add a backend source registry that defines static, allowlisted documentation sources by canonical language id.
- Source entries must include stable ids, canonical language ids, display names, provider labels, source trust tier, seed policy, allowlisted domains, seed URLs, topic tags, and notes/disclosure where needed.
- Registry coverage must include all mainstream language ids from `LANGUAGE_CAPABILITIES`: `python`, `javascript`, `typescript`, `java`, `go`, `csharp`, `rust`, `cpp`, `sql`, `html`, and `css`.
- Trust tiers must distinguish official/project-accepted official documentation, trusted/de facto documentation, and internal sources.
- URL allowlisting must be explicit and domain based; source seed URLs must match their declared allowlisted domains.
- Registry helpers must support retrieving all sources, retrieving sources by language, retrieving a source by id, and listing allowlisted domains/seed URLs for downstream fetcher work.
- Registry validation must catch unknown language ids, duplicate source ids, missing seed URLs, missing domains, and seed URLs outside their allowlisted domains.
- The implementation must reuse the existing language capability ids instead of introducing a parallel language taxonomy.

## Acceptance Criteria

- [ ] Backend source registry covers every language in `LANGUAGE_CAPABILITIES`.
- [ ] C++ is registered as trusted/de facto rather than official-only and includes an explicit rationale note.
- [ ] Planned execution languages can be grounded in docs without changing `enabled_for_public_selection`, runtime runner status, or execution support.
- [ ] Every source id is unique and every source seed URL is under an allowlisted domain.
- [ ] Public helper functions return immutable/read-only tuples or copies and degrade to empty tuples for unknown languages.
- [ ] Tests verify full language coverage, source id uniqueness, URL allowlist validation, trust-tier alignment with `source_trust_policy`, and no runtime/public-selection side effects.

## Out of Scope

- Fetching pages over the network.
- Cleaning, chunking, embedding, or indexing external documentation.
- Retrieval ranking and agent citation formatting.
- Replacing existing `teaching_chunks` behavior.
- Enabling TypeScript/Go/C#/Rust/SQL execution or adding new public course languages.

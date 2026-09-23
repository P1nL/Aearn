# Design: RAG Subject and Capability Taxonomy

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child阶段I仍定义operator_locked/fixture-only等原合同。后续自主治理只能消费预登记source/Subject/version授权与release状态，不得通过题库扩域或自动公开生态；若增加v2版本策略必须新合同，不改旧值含义。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

## Boundaries

Add `subject_contracts.py` and `subject_registry.py` under the existing grounding service package. Reuse `LanguageCapability`; do not move current public selection ownership into the new registry.

## Contracts

- `SubjectKind`: language_core, standard_library, framework, library, platform, database, toolchain.
- `SubjectVersionPolicy`: operator_locked for phase 1, with schema room for future fixed/rolling policies.
- `SubjectReleaseState`: implemented, fixture_only, shadow, lesson_only, static_only, executable, planned, unavailable.
- `GroundingSubject`: stable identity, parents, languages, aliases, version policy, trust policy, facets, runtimes, assessments and release state.
- `SubjectCapabilityProjection`: composed server-owned view used by future preflight/adapters.

## Initial Registry

Route families:

- `route.python`
- `route.typescript-javascript`
- `route.web-platform`
- `route.sql`

Fixture-only ecosystems:

- `python.ai-applications`
- `python.fastapi`
- `typescript.nodejs`
- `web.react`
- `web.platform`
- `sql.postgresql-foundations`

The registry must expose immutable tuple/copy helpers, alias resolution and deterministic validation errors. It must not perform I/O at import time.

## Compatibility

Existing `LANGUAGE_CAPABILITIES`, `PUBLIC_COURSE_LANGUAGE_MAP`, seeds and routes continue unchanged. New helpers may derive projections from them but cannot silently enable Rust/C++ or alter the eight current public course ids.

# RAG Subject and Capability Taxonomy

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child阶段I仍定义operator_locked/fixture-only等原合同。后续自主治理只能消费预登记source/Subject/version授权与release状态，不得通过题库扩域或自动公开生态；若增加v2版本策略必须新合同，不改旧值含义。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

## Goal

Add the stable language-to-Subject ecosystem taxonomy and honest capability projection required by RAG 2.0 without changing existing public course selection or learner-visible behavior.

## Dependencies

- Parent requirements and design: `09-03-rag-language-ecosystem-adaptive-retrieval`.
- Existing `LanguageCapability` and public course mappings remain compatibility authority for current routes.

## Requirements

- Add strict immutable contracts for Subject kind, parent graph, aliases, operator-locked version policy, required/optional facets, source trust policy, runtime profiles, assessment capabilities and release state.
- Add a developer-governed registry for four route families and six first-phase ecosystem Subjects.
- All six ecosystem Subjects must be `fixture_only` or equivalent and must be rejected by existing public selection/admission paths.
- Add one server-owned capability projection combining language, Subject, source, lesson, practice, execution, test, review and release states.
- Validate unique ids/aliases, known languages, existing parents, acyclic graph, known facets/capabilities and runtime compatibility.
- Preserve `html_css` read compatibility without using it as the generic ecosystem model.

## Acceptance Criteria

- [x] Registry contains the four main route families and six agreed ecosystem Subjects with stable ids.
- [x] Invalid parent cycles, duplicate aliases, unknown language/runtime/facet and inconsistent release states fail deterministically.
- [x] `fixture_only` Subjects cannot become public plan/course candidates.
- [x] Existing language aliases, public course ids and capability tests remain unchanged.
- [x] Projection distinguishes implemented/fixture-only/shadow/lesson-only/static-only/executable/planned/unavailable without exposing internal-only fields publicly.
- [x] Focused tests, Ruff and Mypy pass.

## Out of Scope

- Database schema or corpus rows.
- Source fetching, retrieval ranking or coverage calculation.
- Public ecosystem course activation.
- Desktop UI changes.

# D final internal acceptance and C/D closeout

## Result
**D internal acceptance passed.** The final runner returned `passed_internal_only`; a separate DB read confirmed both parent and successor runs are naturally `completed`, each with exactly one successful draft capability. This is not a manufactured terminal or a re-labelled failed run. See `d-final-acceptance.json` for UTC timestamp, exact coordinates, usage and assertions.

- Parent draft: `ff77fb4a-8167-4c5b-94f2-45fcff37eb3f`, source run `0c8d77ba-70c4-4a58-9d7a-89a6245e9c27`.
- Successor draft: `a23e03e8-4a45-4106-9222-c9f8992542a7`, version2, source run `0f4aa28c-694c-494f-9fb4-6bd99a62d6c6`; exact predecessor and all goal hashes preserved.
- One binding: `sql.queries/supplementary_explanation`, digest `0de1ebca9c60ac52a67ae292eaf753dc5a314d660d6355e60666161c88fcf222`; runner reauthorized the persisted binding against current source/corpus authority after the write.
- Semantic review: `a764807d-37e4-4897-82a5-00d1f32a77b6`, settled, consistent/supported, correlated with accepted provider receipt.
- Current source is Tavily-extracted Markdown in corpus `dfcd678c-7eaf-44f1-b495-cc2d5a8577be`, not origin HTML/TLS proof. Queries supplementary is ready; schema, main and assessment remain gaps. Source coverage stays required2/covered1/gap1/partial=true.
- No new Search/Extract/direct GET in final verification. Old direct source attempt/capture histories hash-match the baseline; five named prior failed model runs remain failed.

## Repairs actually exercised
1. A current-revision verified plan save removes only the consumed draft affordance, retains Skill/receipt, and rejects even an oversized raw duplicate before payload parsing. Model completion remains required.
2. Only the verified plan acknowledgement phase disables DeepSeek thinking; initial selection/drafting and formal input/output limits remain unchanged. Final parent and successor acknowledgement usage both report reasoning0.
3. Internal material planning uses new Skill/capability1.1.0 (raw1024/escaped6146, action input65536), selected only by trusted exact catalog context. Legacy Skill1.0.3/cap1.0.0 and unrelated capability/effect limits remain intact. Old published hashes were independently checked.
4. Existing pure Compact profile/module validation now precedes paid semantic review and action writes. In this actual successful run, an overlong `pace_summary` was rejected early with maxLength240 guidance, the real model repaired it, and only the valid replacement underwent semantic review and persistence. No domain limit was increased.

## Acceptance mapping
| Criteria | Final evidence |
|---|---|
| D-AC1 | Internal server opt-in only; ordinary planning keeps legacy contract, public consumer remains off. Existing zero-call/public-boundary evidence retained. |
| D-AC2/3 | Real source -> real parent -> current feedback -> real successor -> completed, unique draft and exact predecessor/goal/source coordinates. |
| D-AC4/5 | Only exact approved supplementary evidence bound; main/schema/assessment gaps retained, no whole-page authority. |
| D-AC6/7 | Existing same-connection/fence/immutability tests plus final persisted binding current-authorization reread and separate DB confirmation; prior failures/source history preserved. |
| D-AC8 | Offline, synthetic PG, real internal pass, public/E/Gate and unknown monetary usage explicitly separated. |

## Focused verification
- Final pure-domain/version/semantic/receipt/completion subset: **9 passed**.
- Version/catalog/capability/wire adjacent subset before the final domain patch: **32 passed**; no claim that all old broad tests were rerun.
- Final dedicated PG: **3 passed, 17.15s**, using verified `aearn_rag260_c_d_postsave_check_20260929`, not business5432. Earlier small-window and missing-optional-schema fixture failures were corrected only in test settings (physical16384/dynamic12000) and preserved in the investigation.
- Ruff app/tests/C-D infra, full Mypy **329 files**, offline lock check and diff check passed.
- GPT-5.6 Sol independently reviewed version selection, legacy compatibility, exact current-revision receipts and fixtures. Its host quota then denied further agent work during the pure-domain patch; no model switch or top-up. Main completed the partial patch, fixed its type annotation, added the two focused shape cases, inspected ordering/diagnostic safety, and ran final tests/real acceptance. Independent approval is not falsely extended beyond its reviewed snapshot.

## Usage and scope
Final chain used parent3 + successor5 = **8 actual model HTTP calls**, including the actual repair and semantic review. Historical cumulative total is **69**, within this explicit window's cap71; all earlier failed attempts and their usage remain in the project register. Currency costs remain unknown/user-monitored, not zero. Source acquisition was reused rather than billed again.

User explicitly authorized repair, current/prior closeout and worktree commit. Commit scope is accumulated C/D implementation, related tests/infra/specs/policy and the pre-existing small Codex verbosity setting. Runtime files, credentials and full source bodies stay excluded. C had already completed its isolated ACs and was awaiting commit/archive; both C and D can now close. RAG parent/future E, public production rollout, scoring and Gate are not marked complete. No remote push is authorized or performed.

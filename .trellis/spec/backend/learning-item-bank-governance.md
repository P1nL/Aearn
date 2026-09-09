# Learning Item Bank, Review, and Publication Governance

## 1. Scope / Trigger

Apply this contract whenever code creates, compiles, validates, imports, reviews, pilots, publishes, quarantines, retires, or queries a Learning Item. It also applies when adding curated source files, item-kind validators, reviewer roles, pilot telemetry, human approvals, or Practice materialization.

The Learning Item Bank is the immutable content/publication authority used by later Tutor Artifact selection. It does not replace ExerciseVersion/private rubric, Attempt, scorer, TeachingSession, Lesson Gate, ReviewSession, or mastery/progress authority.

## 2. Signatures

### Source and compiler

```text
aearn/services/api/app/services/learning/item_bank/sources/curated/*.{json,yaml}
learning_item_source_v1
learning_item_compiler_v1
learning_item_validation_v1
```

```python
compile_curated_learning_item_catalog() -> CompiledLearningItemCatalog
validate_learning_item(source: LearningItemSourceV1) -> LearningItemValidationReceiptV1
import_curated_learning_item_sources(conn, *, source_root=None, imported_at=None)
```

### PostgreSQL

```text
tutor_learning_item_blueprints
tutor_learning_items
tutor_learning_item_versions
tutor_learning_item_public_contents
tutor_learning_item_private_contents
tutor_learning_item_validation_receipts
tutor_learning_item_import_receipts
tutor_learning_item_publication_events
tutor_learning_item_review_reports
tutor_learning_item_review_adjudications
tutor_learning_item_pilot_receipts
tutor_learning_item_human_approvals
tutor_learning_item_practice_materializations
```

### Repository and governance

```python
PostgresLearningItemBankRepository.import_validated_source(...) -> LearningItemImportResult
PostgresLearningItemBankRepository.published_candidates(..., available_capabilities, limit<=8)
LearningItemGovernanceService.prepare_review(handle=...)
LearningItemGovernanceService.record_review_bundle(...)
LearningItemGovernanceService.start_pilot(...)
LearningItemGovernanceService.record_pilot_telemetry(...)
LearningItemGovernanceService.approve_high_risk(...)
```

Feature flag: `LEARNING_ITEM_BANK_AGENT_REVIEW_ENABLED=false` by default.

## 3. Contracts

- Source files are Git-owned UTF-8 JSON/YAML. Loading rejects duplicate keys, non-finite numbers, oversized files/catalogs, excessive depth/nodes, symlink/junction components, path escape, drive-qualified paths, unsafe suffixes, and empty source roots.
- Compilation records exact source-byte hash, normalized source hash, canonical source/content hashes, deterministic UUID identities, and the stable `li:<sha256>` handle. Reordering files does not change the catalog digest.
- Public and private content are separate strict `extra=forbid` contracts. Public data may contain learner-visible prompt, starter content, safe source references, difficulty, interactions, and H1-H3 hints; it never contains standard answers, hidden tests, private rubric, scorer evidence, reviewer/provider bodies, commands, paths, images, or secrets.
- Every imported receipt is revalidated by the repository. A caller-supplied validation receipt is not authority unless it exactly equals the deterministic receipt recomputed from the source.
- Deterministic validation covers the complete canonical check set: schema, source references, difficulty, public/private boundary, Markdown safety, hint leakage, Practice contract, standard answer, starter-not-passing, runtime/event behavior, and scorer consistency.
- HTML/browser fixtures may use the deterministic browser rule seam. Legacy SQL v1 requires `sql_query_test`, a single read-only query, bounded literal setup statements, and exact expected results. Structured `sql_v2` instead publishes only exact tables/columns/types/PK/FK metadata plus one public dataset; every visible/hidden private case owns an independent dataset and exact typed table expectation. Demonstrations require `browser_preview` and exact event or bounded static duration. Unsupported code runtimes fail closed; validation never shells out or invokes Docker by default.
- Structured SQL tables use simple bounded identifiers and INTEGER/REAL/TEXT columns. A foreign key references exactly one published primary-key column with the same declared type. Every dataset contains every published table exactly once, validates row width/type/nullability/PK uniqueness/FK integrity, limits public rows to 50 and every private table to 200, and remains within the 65,536-byte safe-table payload boundary.
- The shared catalog tables are immutable/append-only infrastructure and belong in the shared cutover allowlist, not user export/reset/delete.
- Import is deterministic and idempotent by exact source path/content/validation identity. Reusing an import key, item key/version, handle, or hash with different content fails closed.
- Curated import ends at `machine_verified`. No item becomes an online candidate until review, pilot, and risk gates append a valid `published` event.
- Review input is blind and bound to one exact handle/content hash. It excludes creator identity and peer reports. Six unique roles are required: curriculum, difficulty, technical, ambiguity, security, and adversarial.
- The normalized creator identity cannot review the same version. Reviewer identities are unique per version/policy, and reviewer ports may arrive in any order while reports are persisted in canonical role order.
- Deterministic failure, security, unique-answer, rubric mismatch, or data leakage is an absolute blocker. Adjudication cannot override blockers, major/critical findings, missing roles, stale hashes, or medium-risk missing machine execution evidence.
- A changed item creates a new immutable version/content hash. Old validation, reports, adjudication, pilot telemetry, or approvals cannot authorize the successor.
- Publication path is `machine_verified -> agent_reviewed -> pilot -> published`, with safety transitions to `quarantined` or `retired`. All transitions use predecessor/state-version CAS and idempotent request hashes.
- Low risk may promote after a complete successful pilot. Medium risk requires machine execution evidence, all six reviews, and a complete successful pilot. High risk additionally requires exact current-pilot human approval; lower risk must not request human approval.
- Pilot telemetry is cumulative and cannot rewind. Security/leakage incidents retire; ambiguity, difficulty mismatch, or unexpected outcomes quarantine; incomplete cohorts remain collecting.
- Publishing a non-demo item atomically materializes/replays the exact existing `tutor_exercise_versions` and `tutor_exercise_private_rubrics` authority. Demo items remain Learning Item authority. Materialization never creates Attempt, score, mastery, or progress evidence.
- Online selection returns at most eight `published` safe candidates and requires an explicit compatible capability set. It returns only handle, kind, purpose, knowledge/language, difficulty, title/summary, capabilities, and allowed interactions.
- Reviewer/provider exceptions are mapped to safe failures without chaining raw provider details. Routine tests use fake reviewer ports only.
- Review approval is not proof that the production scorer rejects every known counterexample. Before promoting an item with an identified scoring risk, execute the exact counterexample through the real deterministic scorer. A confirmed factually incorrect response passing the threshold is a rubric/validation blocker even if an individual reviewer classified the hypothetical risk as minor. Retain reports and hash-bound audit evidence; quarantine the affected immutable version rather than rewriting it or fabricating a successful pilot.
- Controlled model-only pilots must retain the exact public-only input, observed response, source hash, actual scorer result and usage locally. They are not human learner cohorts or usability evidence. Pilot counts must be derived from actual observations, preserve the existing risk thresholds, and never be copied from review votes or invented test-user counts.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Duplicate JSON/YAML key, non-UTF-8, non-finite value, oversized/deep source | compiler failure without echoing source content |
| Symlink/junction, absolute/drive path, path escape, empty import root | fail closed before parsing/import |
| Public payload contains answer/test/rubric/unsafe Markdown or Hint leaks answer | deterministic validation failure |
| Standard answer fails or starter already passes | deterministic validation failure |
| SQL mutation/multiple statement/unsafe setup/wrong profile | deterministic validation failure |
| Demo event/duration or profile mismatch | deterministic validation failure |
| Knowledge answer is ambiguous or tests disagree | deterministic validation failure |
| Model-review receipt/scorer/content hash mismatch | deterministic validation failure |
| Import receipt differs from recomputed validation | `LearningItemImportConflict`; no partial rows |
| Creator equals reviewer, including case variants | reject before reviewer invocation |
| Missing/duplicate reviewer role or report bound to another hash | review/adjudication conflict |
| Any absolute blocker or major/critical finding | adjudication cannot approve |
| Medium risk lacks machine execution evidence | adjudication cannot approve |
| Pilot telemetry rewinds counters or disagrees with policy decision | PostgreSQL rejection |
| High risk publishes without current successful pilot approval | PostgreSQL/governance rejection |
| Low/medium risk supplies human approval | governance rejection |
| Published item becomes quarantined/retired | immediately absent from candidate query; immutable history retained |
| Candidate query omits capabilities | return no candidates, not an optimistic superset |
| Same import/transition key with different request hash | idempotency conflict |

## 5. Good / Base / Bad Cases

- **Good:** Bootstrap compiles five curated source files, recomputes deterministic validation, imports each immutable version once, and a second bootstrap replays without duplicate rows.
- **Good:** Six distinct fake reviewers receive identical blind input, all approve, adjudication records exact report hashes, pilot succeeds, and a low-risk code item materializes one exact Practice authority before publication.
- **Good:** A high-risk item remains in pilot after successful telemetry until an exact human approval bound to the current pilot receipt is recorded.
- **Base:** Agent review is disabled. Machine-verified catalog history remains readable, but review/pilot/publication mutations stop and candidate lookup returns only previously published versions.
- **Bad:** Trusting a generated draft or reviewer majority after deterministic/security failure.
- **Bad:** Publishing directly from `machine_verified`, reusing old reports after content changes, or returning private item JSON to Teaching candidate context.
- **Bad:** Treating a demo as an Exercise/Attempt, or letting item publication update mastery/progress.

## 6. Tests Required

- Compiler tests for duplicate JSON/YAML keys, UTF-8, size/count/depth/node bounds, non-finite values, symlink/junction/path escape, empty roots, exact byte hashes, and deterministic catalog digest.
- Validator tests for every item kind, public/private markers, malicious Markdown/URL, Hint leakage, difficulty/source mismatch, standard-answer success, starter failure, legacy SQL read-only/setup policy, structured SQL schema/dataset/FK/bounds and public-hidden independence, demo event/duration, knowledge uniqueness, and model-review receipt/scorer consistency.
- Bootstrap twice with all curated sources; assert 13 shared tables, constraints, indexes, immutable/append-only triggers, and exhaustive shared cutover classification.
- Import tests for exact replay, conflicting keys/hashes, forged validation receipt rejection, source path rules, and immutable version/public/private rows.
- Review tests for six blind roles, order independence, case-insensitive self-review denial before invocation, unique reviewers, safe provider failure, report-hash binding, and old-report invalidation after a new content version.
- Adjudication tests must prove no consensus overrides deterministic/security/uniqueness/rubric/data-leakage blockers or major/critical findings.
- Real PostgreSQL tests for low and medium pilot promotion, high-risk current-pilot human approval, cumulative telemetry, quarantine, retirement, replay/conflict, and retained historical public/private rows.
- Materialization tests assert one exact ExerciseVersion/private rubric for non-demo items, no duplicate on replay, and no Attempt/mastery/progress writes.
- Candidate tests require explicit capability compatibility, exclude machine-only/pilot/quarantined/retired versions, omit private fields, respect filters, and cap at eight.
- Run the complete serial API pytest suite, Ruff, Mypy, dependency lock, Trellis validation, and `git diff --check`. Real provider and Docker conformance require separate approval.

## 7. Wrong vs Correct

### Wrong

```python
if majority(review_reports).approved:
    repository.append_publication_state(handle, next_state="published")
return repository.all_items(knowledge_key)
```

This ignores deterministic/security vetoes, content-hash binding, pilot/risk policy, human approval, Practice materialization, and safe candidate filtering.

### Correct

```python
subject = governance.prepare_review(handle=handle)
reports = orchestrator.review(subject)  # six blind, independent fake/offline ports
adjudication = governance.record_review_bundle(
    subject=subject,
    reports=reports,
    adjudication_key=adjudication_key,
)
governance.start_pilot(subject=subject, adjudication=adjudication)
pilot = governance.record_pilot_telemetry(subject=subject, telemetry=telemetry)
if subject.risk_tier == "high":
    governance.approve_high_risk(subject=subject, pilot=pilot, approval=approval)
```

The correct path revalidates exact content, preserves immutable evidence, applies absolute blockers and risk policy, materializes existing Practice authority only at the authorized publication boundary, and exposes only published safe handles.

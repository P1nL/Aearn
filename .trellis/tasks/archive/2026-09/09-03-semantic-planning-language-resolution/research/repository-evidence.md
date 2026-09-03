# Repository Evidence: Semantic Planning Language Resolution

## Observed runtime result on 2026-09-03

A real local plan-drafting request created after the learner wrote `我想做langchain架构的agent` persisted:

- `selection_scope=full_catalog`
- `selection_reason_code=no_intent_signal`
- `intent_policy_version=planning-language-intent-v1`
- `recommended=null`
- eight active course-language options

The model's learner-facing answer recognized LangChain, but the server presentation still used the full catalog. No user/conversation UUIDs are retained in this task evidence.

## Exact cause

- `planning_intent.py:63-92` defines a bounded keyword intent alias table without LangChain/Agent/LLM concepts.
- `planning_intent.py:121-165` combines explicit aliases and deterministic intent tags, then maps no signal to all active course IDs.
- Direct execution against the exact phrase returned `explicit=()` and `intents=()`.
- `interaction.py:836-847` calls `resolve_for_run()` without `model_hint`, so model semantic understanding does not reach request generation.
- `planning_questions.py:103-125,228-254` turns candidate course IDs into exact public language options and uses the entire active catalog when resolver candidates are broad.

## Existing seams to reuse

- `planning_intent.py:106,167-209,247-294` already has an optional strict model-hint seam, but v1 accepts closed intent tags only.
- `plan_tools.py:280-329` returns the authoritative missing-fact descriptor to the model and can add bounded server-built language candidates.
- `decision_protocol.py:209-268,571-657` owns strict provider wait-for-input schema and assembly into `TutorDecision`.
- `planning_facts.py:761-809` owns the planning question decision gate before persistence.
- `interaction.py:756-948` atomically writes the Tutor message and exact durable request presentation.
- Desktop already renders persisted `single_select` or `text` requests and does not infer recommendations.

## Source-of-truth constraints

- `docs/architecture/api-contract.md:677-681` requires deterministic input resolution, durable exact options, and server-owned model-hint boundaries.
- `docs/product/frontend-interaction-spec.md:339-343` requires zero default selection and exact durable replay.
- `.trellis/spec/backend/codex-runtime-sidecar.md:527-534` currently documents deterministic v1 and must be updated for bounded semantic v2.
- `.trellis/spec/frontend/type-safety.md:573-577` requires exact DTO parsing and no internal candidate evidence in public fields.

## Dirty-tree and branch constraint

Planning runs on `codex/tutor-skill-catalog-eol-regression`; the new task uses that branch as its base so a new immutable Skill bundle inherits the committed raw-byte EOL rules. Do not modify dirty historical Skill bundles or unrelated Trellis/generated files.

# Adaptive Exercise Template System Design

## Scope

This task introduces an adaptive exercise pipeline:

1. Select a canonical template.
2. Generate a bounded candidate variant.
3. Validate the candidate with the matching runner.
4. Cache verified variants.
5. Fall back to canonical templates when anything is unsafe or invalid.

The system is local-only and user-scoped where variants depend on learner history.

## Existing Baseline

Current exercise creation is mostly deterministic:

- `exercise_repository.py` owns `_exercise_template(...)` for normal learning exercises.
- `exercise_repository.py` owns `_exercise_template_from_review_seed(...)` for review seeds.
- `review_seed_bank.py` can generate and materialize review variants.
- Runner validation exists for Python, Node/TypeScript, and browser HTML/CSS.

The missing product contract is mandatory pre-use runner validation, versioning, and reusable cache semantics.

## Proposed Components

### Canonical Template Catalog

Add a template catalog module, for example `exercise_templates.py`.

Each canonical template should include:

- `template_id`
- `template_version`
- `language_id`
- `runtime_tier`
- `exercise_type`
- `knowledge_point_tags`
- `difficulty`
- `starter_code`
- `solution_reference` or validator reference
- `visible_test_cases`
- `hidden_test_cases`
- fallback payload
- safety constraints

The initial catalog can be code-owned. A database-backed authoring UI is out of scope.

### Model-Assisted Candidate Generator

Add an adaptive generator service, for example `adaptive_exercise_service.py`.

Inputs:

- user id
- plan id
- knowledge point
- runtime profile
- recent visible attempt facts
- weak points
- supported exercise types
- target runner capability

Output:

- candidate exercise payload
- generator version
- source: `model_candidate`, `deterministic_fallback`, or `fallback_template`
- model id when a model was used
- prompt/template version
- safe reason/failure metadata

The first implementation should call a model to produce a structured candidate, but only inside the selected canonical template envelope. The model can vary learner-facing wording, names, values, data rows, and scenario framing. It cannot change the runner family, unsupported language, required schema, hidden-test redaction policy, safety constraints, or validation contract.

Deterministic parameter substitution remains as:

- provider failure fallback
- invalid model response fallback
- repeatable test fixture generator
- local development path when model/API is unavailable

Model output must be parsed into a typed candidate object before validation. Invalid JSON, unsupported fields, unsafe text, missing required fields, hidden-data leakage, or changed template-owned fields all produce fallback behavior.

### Runner Validation

Before materialization, the service should validate candidates by running the canonical solution or validator reference through the matching runner.

Validation must check:

- runner exists and supports execution/tests
- visible tests pass
- hidden tests pass
- runtime status is not timeout/runtime_error/unsupported
- public serialization redacts hidden data
- generated candidate has required fields and safe text

If validation fails, the service uses the stable fallback template.

Model-assisted candidates and deterministic candidates use the same validation path. There must not be a separate fast path that skips runner validation for model output.

### Cache and Versioning

Recommended persistence is an additive user-scoped table, for example `exercise_variant_cache`.

Suggested fields:

- `id`
- `user_id`
- `knowledge_point_id`
- `template_id`
- `template_version`
- `generator_version`
- `runner_key`
- `runtime_tier`
- `variant_hash`
- `status`
- `exercise_payload_json`
- `validation_report_json`
- `failure_code`
- `created_at`
- `last_used_at`
- `deleted_at`

Only `validated` variants should be reused. A version mismatch should be a cache miss.

Because variants can be learner-specific, local user reset/delete/export must handle this table consistently.

### Materialization

After validation, materialize the verified payload into existing `exercises`, `code_blanks`, and `test_cases` tables. Store adaptive metadata in `exercises.metadata_json`:

```json
{
  "adaptive_variant": {
    "template_id": "python-return-v1",
    "template_version": "1.0.0",
    "generator_version": "adaptive_template_v1",
    "variant_hash": "...",
    "validation_status": "validated",
    "source": "model_candidate",
    "model": "configured-model-id"
  }
}
```

Fallback exercises should record `source="fallback_template"` and a learner-safe fallback reason.

### Redaction Boundary

The learner-facing exercise and result payload must not expose:

- solution references
- hidden expected outputs
- hidden fixture details
- raw prompts
- provider payloads
- internal runner logs
- validation traces

Debug/test metadata can store bounded safe failure codes.

## Compatibility

- Existing static templates must continue working.
- Review seed bank materialization can be adapted incrementally, but should not regress M4 review tests.
- SQL templates depend on `06-02-sql-query-runner`.
- Public route availability should continue to be governed by the capability matrix and course content.

## Rollback

- Disable adaptive generation and use existing deterministic templates.
- Disable model-assisted generation and use deterministic fallback or existing templates.
- Ignore or archive variant cache rows.
- Keep canonical fallback templates as the stable product path.
- Preserve review seed bank behavior if adaptive validation has to be reverted.

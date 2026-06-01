# Design

## Scope

This task models human interrupt checkpoints as typed graph runtime contracts. It does not add a durable approval queue, a new frontend component, or LangGraph-managed product state.

The checkpoint is a soft graph intent:

- The graph decides that a transition or action needs learner confirmation, clarification, or safety handling.
- The graph emits bounded checkpoint metadata.
- The adapter converts the checkpoint to `IntentType.FEEDBACK_REQUEST` with target `human_checkpoint`.
- The service validates the intent through the existing graph boundary and continues to own public response rendering, idempotency, and durable writes.

## Contract Shape

Add `GraphHumanCheckpoint` to `graph_runtime_contracts.py` with:

- `checkpoint_id`
- `checkpoint_type`: `approval`, `clarification`, or `safety`
- `reason`
- `prompt`
- `scope`
- `metadata`

Builder helpers bound and redact every field using the existing graph redaction rules.

## Learning Orchestration Cases

The learning orchestration graph will attach checkpoint metadata in these internal cases:

- Early practice request before concept completion: approval checkpoint for skipping the concept check.
- Readiness check fails the Feynman heuristic: clarification checkpoint asking for a more concrete explanation.
- Direct-answer / complete-code request: safety checkpoint for answer-seeking handling without unlocking a new tool path.

Existing public behavior remains unchanged: early practice can still unlock with the current skipped concept-check tool sequence; ambiguous answers still remain in concept flow; direct-answer requests are handled by the existing tutor guardrails/prompt policy.

## Boundary

Allowed learning graph intents add only:

- `IntentType.FEEDBACK_REQUEST: ("human_checkpoint",)`

The service does not execute durable writes from this intent. It validates that the graph emitted a scoped checkpoint and ignores the internal metadata for public rendering.

## Rollback

Rollback is removing the new checkpoint dataclass/helper, removing learning orchestration checkpoint payloads, and removing the added tests. No database cleanup is required.

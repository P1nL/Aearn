# Diagnostic Blind Solve Admission

## 1. Scope and trigger

User-approved new native finite policy on2026-10-06. A single completed blind
solution can be wrong without deciding that the question is invalid. This is a
new explicit branch, not a global deletion of legacy strict checks. Source of
truth remains the runtime/database docs indexed by docs/README.md.

## 2. Policy and contract entry points

- `diagnostic_policy.py::AutonomousEvidencePolicyV3` identifies
  `autonomous_evidence_policy_v3` with `blind_solve_mode=completed_diagnostic`.
- `SharedGenerationPipeline.prepare_generation(..., evidence_policy=AutonomousEvidencePolicyV3())`
  freezes `SharedGenerationPolicyBindingV3` before the first original author
  reservation. `GenerationRequestV2` itself retains its original shape/hash.
  The binding table is immutable shared metadata, never a new accounting root.
- `ReviewBundleV3` retains the genuine completed `BlindSolveReceiptV2` and the
  same six independent role reports; no forged pass flag or reconstructed run.
- `AdmissionEvaluationV3.diagnostic_warnings` retains `blind_solution_incorrect` when the
  exact completed blind score is false and all independent hard requirements pass.
- Old V2 policy, bundle, evaluation JSON/hash and default behavior stay unchanged.
  Type-dispatched helpers must not erase subclass/new-version fields.
- Policy is frozen in the real generation/artifact/job context and verified at
  review,493facts,494publication/current-read and501consumption. An extra caller
  boolean or a policy string pasted onto an old receipt is not authorization.
- `finite-public-spec-v3` is a presentation version, not the admission policy.
  It cannot select or authorize diagnostic blind behavior on its own.
- The bounded task operator selects `--admission-policy strict-v2|diagnostic-v3`.
  Default strict plans retain their original JSON/hashes. Only explicit diagnostic
  plans add exact mode/version/hash metadata, frozen before source/provider work
  and rechecked against the original generation policy on continuation/readback.
  Neither choice changes canonical obligations, accounting limits or lease rules.

## 3. End-to-end behavior

After current deterministic/finite checks, perform the original bounded blind
attempt once. On a genuine completed score (true OR false), the V3 path continues
the original six-role independent review. Neither blind output nor earlier role
reports become reviewer inputs. Preserve author/solver/reviewer separation.

Admission still verifies current source/claims, exact source/content/policy/runtime,
all required positive/negative/equivalent/scorer/ambiguity controls and role/risk
evidence. A role or machine blocker cannot be outvoted. Missing/uncertain evidence
is pending, not inferred success. High-risk adapters and independent second-bundle
requirements remain intact; no new statistical-independence claim.

Only when all hard conditions pass can V3 return `eligible_internal` with the
warning. Original publication authority remains separate; no second publisher,
public consumer release, user Attempt/Gate or mastery update is introduced.

## 4. Outcomes and error matrix

| Case | Required result |
| --- | --- |
| V3 completed wrong + all independently verified hard evidence | Internal eligible with preserved warning/false blind score |
| V3 completed wrong + missing source/probes/roles/runtime | Pending or existing hard rejection; never eligible |
| V3 completed correct + deterministic or material review failure | Existing hard rejection |
| Timeout/transport/malformed/absent blind completion | Explicit run/evidence pending; never fabricated wrong/correct receipt |
| V2 completed wrong | Original strict rejection, original hashes |
| V2/V3 cross-splice, changed policy/hash, copied capability | Reject before effects |
| Expired lease/source or reset epoch | Reject; new policy does not restore old authority |
| Six reviews disagree or leave blocking ambiguity | No internal eligibility; no majority-vote shortcut |

The first increment may retain incomplete blind invocations as pending. Do not
claim a missing-native-receipt infrastructure path supports publication simply
because completed-wrong is now supported.

## 5. Accounting, migration and history

One original bounded reservation/settlement flow; provider IO is IDLE and reports
retain UNKNOWN accounting where required. No repeated blind solves, new wallet,
canonical-root fork, profile/window/lease expansion or history erasure.

Old440–504 SQL bytes are immutable. Any505 extension must pin the exact supported
effective function baseline, preserve unrelated fences and fail unknown shapes.
No mutation of existing candidate/review/publication rows to adopt V3. Historical
`blind_solution_rejected` remains historical failure, not a V3 approval.

`tutor_item_supply_shared_generation_policy_bindings` references the existing
candidate/root/job/request/blueprint/profile/lease generation. It is included in
the shared inventory and excluded from learner purge/export.505 refuses insertion
after an author reservation, a generated artifact or an adopted continuation.

## 6. Required verification

Focused V2 golden/default regressions, completed-wrong positive plus each hard
negative, peer-input isolation, mixed-version tamper and native policy/warning
round-trip tests. Main alone performs real SQL compilation/ordered replay with
original-column data hashes and full rollback/function restoration. SQL shape
tests do not equal real PostgreSQL execution; fixtures do not equal live delivery.

Record implementation, independent review, schema application and real-provider
acceptance separately. No commit/push/deploy/archive is implicit in policy approval.

## 7. Wrong vs correct

Wrong: set blind.score.passed=true, delete a hard `if` only at the pipeline entry,
relabel old failing evidence, or trust six agreeing models over failed machine
checks. Correct: preserve the genuine observation, apply a fully bound new policy,
and require unchanged independent correctness and publication authorities.

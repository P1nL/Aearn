# Formal runtime profile alignment — 2026-09-28

## Scope and status

Changed only `aearn/infra/rag-d-live/{run.py,prepare.py,real_parent.py,parent_provenance.py,README.md,tests/test_run.py,tests/test_real_parent.py}`. No product context/protocol defaults, source permissions, DB rows, real provider requests, source fetches, commit, push, or public activation. This is **offline harness repair**, not C→D live acceptance. Earlier 2026-09-28 failures/unknown usage remain in the immutable ledger; v1 and failed audits cannot become v2 success.

## Root cause and repair

The prior D operator overrode Settings to an isolated `4096` draft output, `8192` input, `2048` dynamic target and forced `thinking_mode=disabled` on every CountedClient call. These are a boundary experiment, not the normal host configuration; they changed both the payload-selection policy and provider protocol observed in prior paid windows. The previous provenance hard-coded those numbers and a combined16 cap even though the operator ledger had advanced to20. The generic guard rejected the formal decision limit above4096. This made a successful low-budget run incapable of proving a normal-config run, and failures could not distinguish host/container configuration drift from provider structured-output behavior.

The default path now imports an allowlisted, nonsecret **host effective Settings snapshot** and rejects any low-budget overrides. The current host policy reported by the main session is DeepSeek Flash physical context field1,000,000, but resolved ordinary application capacity192,512, reserve61,440, decision limit16,384, input hard limit131,072, dynamic target130,688; protocol reserve128/safety256; mode targets16,000/64,000/96,000/130,688; warning0.8/critical0.95; expansions1; repair thinking disabled true. `runtime_profile(Settings())` exports *both* the raw allowlisted context knobs and computed effective fields. The process validates exact keys/types, Settings validation, computed values and provider type/model against its separate root-private provider file. It then sets only allowlisted nonsecret process-local env fields so application-created Settings instances see the same profile. The fixed `CountedClient` no longer forces first-decision thinking; product gateway/repair logic owns that choice.

`--profile boundary-test` is a separate, explicit test profile. Both stages require `--draft-output-tokens` and `--input-limit-tokens` to reduce the host snapshot; optional `--dynamic-target-tokens` can select2048. It records the actual reduced effective policy and cannot be presented as formal acceptance. No silent default reduction remains. Existing phase HTTP max1..8, underlying per-client attempts1, shared URL POST guard, and wall30..300s are unchanged. The operator supplies `--prior-http-attempts N --cumulative-http-cap M --max-http K` with `N+K<=M`, reconciled against the running ledger; the successor requires N to include parent actual attempts and the v2 provenance checks this relation. This is a bounded operator declaration, **not** an automatic global account cost ledger or proof that unknown monetary cost is zero.

## Exact non-paid export and launch API

1. In the host API venv and actual effective environment, run `python -B ../../infra/rag-d-live/run.py --export-runtime-profile`. It prints **only** the safe profile JSON. Inspect it (not the full `.env`), and stream it via stdin into a separate root0600 tmpfs file `/run/d-live/runtime-profile.json`. Keep the provider JSON/DSN separately root-private. No credentials or snapshot contents are passed as Docker environment, argv, image layer or log entry.
2. After the independently verified current C admission and runtime cutover, invoke `prepare.py --execute --real-parent --control-config /etc/rag-c-control/config.json --provider-config /run/d-live/provider.json --runtime-profile /run/d-live/runtime-profile.json --parent-provenance-out /run/d-live/parent-provenance.json --prior-http-attempts N --cumulative-http-cap M --max-http K --wall-seconds 240`. The parent output is v2 and includes exact durable provider receipts, status, profile and actual usage; the request still uses two independent declared modules `sql.schema` optional and `sql.queries` core, not an invented or cropped one-module plan.
3. Only after actual parent persistence, invoke `run.py --execute --provider-config ... --runtime-profile ... --control-config ... --receipt ... --service-public-key ... --capture-id ... --corpus-id ... --admission-run-id ... --user-id ... --session-id ... --conversation-id ... --parent-draft-id ... --target-run-id ... --target-input-revision ... --parent-kind real_provider --parent-provenance ... --prior-http-attempts N2 --cumulative-http-cap M --max-http K2 --wall-seconds 240`, with `N2=N+actual_parent_HTTP` and `N2+K2<=M`. Both stages audit `profile=formal` and the resolved effective policy. This API does not itself grant source/model cost approval; main retains that gate.
4. For **boundary only**, add `--profile boundary-test --draft-output-tokens 4096 --input-limit-tokens 8192 [--dynamic-target-tokens 2048]` to each stage. An old v1/failed artifact is rejected rather than rewritten.

Exact CLI skeleton for the full-real successor (replace each angle-bracket coordinate with independently verified values; never paste credentials on argv):

```sh
python -B ../../infra/rag-d-live/run.py --execute \
  --provider-config /run/d-live/provider.json --runtime-profile /run/d-live/runtime-profile.json \
  --control-config /etc/rag-c-control/config.json \
  --receipt /run/d-live/current-admission-receipt.json --service-public-key /run/d-live/reviewer-public.raw \
  --capture-id <capture-uuid> --corpus-id <corpus-uuid> --admission-run-id <admission-run-id> \
  --user-id <user-uuid> --session-id <session-uuid> --conversation-id <conversation-uuid> \
  --parent-draft-id <parent-uuid> --target-run-id <target-run-uuid> \
  --target-input-revision <revision> --parent-kind real_provider \
  --parent-provenance /run/d-live/parent-provenance.json \
  --prior-http-attempts <N2> --cumulative-http-cap <M> --max-http <K2> --wall-seconds 240
```

The host exporter CLI only reads effective settings and prints JSON, with no provider call; offline disabled-provider check exited2 safely, and a fake-key configured offline export exited0 with capacity192512 and secret absent from stdout. These are not live provider evidence. The root-private file creation/mount is owned by the main operator; do not send the full `.env` or vendor key into an environment/argument to simplify this step.

## Offline checks and remaining blockers

All `aearn/infra/rag-d-live/tests`: **60 passed, 3 skipped** (environment-dependent preflight cases), with `PYTHON_DOTENV_DISABLED=1`, `LLM_TYPE=disabled`; infra-target Ruff and compileall passed; `git diff --check` reported only line-ending warnings in unrelated existing dirty files. New tests cover formal resolved192512 vs physical1M, 131072 input and16384 decision, strict allowlist/secret rejection, explicit boundary and audited reduction, CountedClient thinking pass-through/cap, cumulative prior cap, and old failed/v1 audit denial. No current C permission or provider protocol acceptance was verified here. Main must reconcile live source expiry, provider configuration, cumulative HTTP ledger, source/DB gate, and whether a fresh formal-profile paid window is appropriate; do not use earlier failed parent responses or skip protocol diagnosis to save time.

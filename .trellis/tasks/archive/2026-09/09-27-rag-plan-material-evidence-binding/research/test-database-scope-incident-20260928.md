# Test database scope incident — 2026-09-28

## Confirmed execution deviation

The wire-contract implementer was instructed not to use a database, but included `tests/tutor/test_tutor_teaching_action_loop.py` in an expanded pytest command. It set `PYTHON_DOTENV_DISABLED=1` and `LLM_TYPE=disabled`, but omitted an explicit `DATABASE_URL` and did not verify the target first. Main stopped/closed that agent and prohibited reruns or cleanup. No claim that failing tests imply rollback is made.

The exact reported command ran from the repo root using the API uv directory:

`uv --directory ./aearn/services/api run python -m pytest -q tests/tutor/test_tutor_provider_gateway.py tests/tutor/test_tutor_action_runtime.py tests/tutor/test_tutor_teaching_action_loop.py tests/tutor/test_tutor_effect_commit.py`

## Main read-only investigation

- Resolving Settings with those same reported environment switches and no explicit database variable returned host127.0.0.1, port5432, database`postgres`.
- Main connected only for a `SET TRANSACTION READ ONLY` inspection, verified database`postgres` and read_only=on. At2026-09-28 18:26:06+08, the query found19 users with the fixture prefix `Teaching ` created between18:21:37 and18:21:53. No user names, IDs, secrets or unrelated user rows were printed.
- `tests/support/teaching_session_support.py` calls full schema bootstrap and explicitly commits test users/tracks/documents. These tests are NOT rollback-only. The original agent did not retain connection identity/SQL logs or a before-state snapshot, so the exact full mutation set and per-row attribution cannot be reconstructed from its report alone. The matching prefix/time is strong evidence of persisted test data, not proof that every matching row belongs exclusively to this run.
- No cleanup, deletion, rollback, grant reset or live-source permission modification was performed as incident response. Do not delete by prefix or time window without an exact reviewed ownership list.

## Containment and next verification

All subsequent database-dependent checks are permitted ONLY in the new explicitly named fixture `aearn_rag260_c_runtime_wire_check_20260928` at the owned WSL PostgreSQL127.0.0.1:55438, useraearn_d. Every command must set `DATABASE_URL` and verify `current_database()` before test collection/bootstrap. The default5432/postgres and the live C database are forbidden test targets. No real provider/source calls are allowed to the checker. Main informed the user of the incident rather than hiding it in a passing-test total.

The expanded run's114 passed/17 failed and separate missing-context test failures are not broad-regression success. The independent checker must diagnose selected-Skill integration and stale test fixtures in its own database; published Skill integrity and business limits cannot be weakened to make tests pass.

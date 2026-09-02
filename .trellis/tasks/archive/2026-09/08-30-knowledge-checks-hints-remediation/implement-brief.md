Active task: .trellis/tasks/08-30-knowledge-checks-hints-remediation

You are already the Trellis implement sub-agent. Implement directly in the current worktree; do not spawn another implement/check agent and do not commit.

Implement the full reviewed Child07 PRD/design/implement artifacts. Reuse the existing artifact authority, item bank, teaching orchestration, inline shell, execution result, and demonstration implementations already committed on this branch. Preserve unrelated pre-existing dirty files and do not include or clean them.

Key constraints:
- structured knowledge-check presentations/responses must be strict, server-authoritative, immutable after response, idempotent/CAS scoped, and public/private redacted;
- implement D1-D5 base difficulty and deterministic validation/selection;
- implement remediation/transfer/disclosure policy per product decisions (original + one remediation max; direct answer not independent evidence);
- implement H1-H3 hint receipts and Desktop overlay popover with manual horizontal paging, first-view receipt semantics, no layout reflow, keyboard/Escape/narrow behavior;
- connect Tutor evaluation/result continuation using existing result/orchestration seams rather than duplicating authority;
- maintain artifacts/__init__.py contracts-only or lazy exports; no eager service/repository/conversation_events imports;
- schema fragment 110 and current tutor_conversation_event_v3 bootstrap compatibility must not regress.

Start by inspecting existing committed patterns and tests. Implement backend, Desktop, tests, and any task-local spec/research notes needed. Run focused tests plus relevant lint/typecheck before reporting. If a true product decision is blocked, report it; ordinary technical choices should be resolved from repository patterns.

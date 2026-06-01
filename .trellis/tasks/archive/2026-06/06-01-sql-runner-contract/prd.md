# SQL runner contract

## Goal

Define the future isolated SQL runner shape for query exercises, dataset setup, teardown, and database safety constraints.

## Requirements

- Depend on `06-01-runner-capability-contract`.
- Define SQL runner capability as planned, not executable in the first registry pass.
- Define future dataset fixture setup, query execution, result comparison, teardown, timeout, and read/write restrictions.
- Require isolated ephemeral data stores or transactions for execution when implemented.
- Define unsupported fallback for SQL execution until safe isolation exists.

## Acceptance Criteria

- [ ] SQL runner contract exists as planned/unsupported capability metadata.
- [ ] Contract prevents executing learner SQL against production or shared application databases.
- [ ] Future implementation requirements include fixture setup, teardown, query type restrictions, timeout, and deterministic result comparison.
- [ ] Unsupported fallback is product-safe and does not pretend SQL execution exists.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.

# Type Safety

> Type safety patterns in this project.

---

## Overview

The desktop app uses TypeScript. Current strictness comes from `tsc` in `aearn/apps/desktop/package.json` and `aearn/apps/desktop/tsconfig.json`.

Runtime API types must follow `docs/architecture/api-contract.md`; do not invent frontend-only enum names for backend fields.

---

## Type Organization

- Keep component-local types near the component until a type is shared.
- Move shared API/domain types into a dedicated module when multiple features need them.
- Future cross-runtime shared contracts may live under `aearn/packages/shared/` only after both desktop and service code need them.
- Keep enum literal unions aligned with API contract values: `language`, `runtime_tier`, `attempt_type`, `runtime_status`, `next_action`, and `fsrs_rating`.

---

## Validation

- No runtime validation library is currently installed.
- Validate unknown API responses at the fetch boundary when the first API integration lands. If a validation library is added, document it in this file and keep it service-wide.
- Do not rely on TypeScript types alone for SSE event parsing; events arrive as strings and must be parsed defensively.
- Surface invalid response shapes as API/contract errors with visible UI feedback.

---

## Common Patterns

- Use literal union types for API enums.
- Use discriminated unions for async UI states, for example `{ status: "loading" }`, `{ status: "error"; code: string }`, and `{ status: "success"; data: T }`.
- Use explicit return types for reusable hooks and API wrappers.
- Prefer `unknown` plus validation for external data over direct `as` casting.

---

## Forbidden Patterns

- Avoid `any` in application code.
- Avoid type assertions for API responses unless immediately preceded by runtime validation.
- Do not duplicate enum strings with different casing or labels.
- Do not model backend-internal Attempt types as visible user labels.

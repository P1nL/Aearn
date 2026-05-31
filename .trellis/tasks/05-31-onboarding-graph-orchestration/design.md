# Onboarding Graph Orchestration Design

## Data Flow

1. Onboarding route validates message and idempotency.
2. Service loads safe onboarding state and current route draft facts.
3. Onboarding graph selects slot extraction, clarification, route generation, revision, or confirmation intent.
4. Service applies graph intents using existing onboarding services/repositories.
5. Public response remains compatible with current onboarding chat and route-card UI.

## Rollback

Use a feature flag to keep the existing onboarding service path available until graph-enabled parity tests pass.

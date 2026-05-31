# Graph Shared Runtime Contracts Design

## Proposed Contracts

- `GraphRuntimeState`: normalized state wrapper for current-session facts.
- `GraphIntent`: typed command-like output such as stage update, tool call request, feedback request, or persistence request.
- `GraphRunResult`: successful graph output containing intents, next stage, diagnostics, and safe prompt context.
- `GraphFallback`: safe failure result used by services to continue or return model-unavailable behavior.

## Boundaries

The shared layer may validate, sanitize, and normalize. It must not open database connections, execute repository writes, call external providers, or emit public responses directly.

## Consumers

Learning, onboarding, and review graph modules should use the same intent and fallback contracts while keeping their domain-specific states separate.

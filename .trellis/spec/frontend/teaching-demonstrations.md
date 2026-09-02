# Teaching Demonstrations

## Authority and rendering

- Render only server-materialized `demonstration_v2` descriptors selected by published Learning Item handle. The client must not accept provider-authored source, steps, events, or durations.
- Demonstration code is read-only in React. Execute interactive source only through the Child04 isolated native Preview host; never evaluate source in the main DOM or add a web fallback.
- Preview interaction evidence includes an exact stable event key, a bounded JSON-object payload, and nonce/generation/sequence identity. Accept only contiguous sequence events emitted by the current child source through its runtime bridge token; reject forged parent messages, synthetic clicks, replay/gap events, and malformed payloads.

## Static visible clock

- Keep unfinished clock state in process memory only so app close/reopen restarts the timer.
- Accrue time only while foregrounded, current, at least 60% visible, and render-ready. Pause immediately when any condition fails.
- Use a 2-3px progress indicator. Reduced-motion mode uses discrete progress without changing elapsed-time or completion authority.

## Completion

- The renderer owns `complete_demo`; generic Artifact action buttons must not expose it.
- Submit exact interactive evidence or visible-clock evidence once and tolerate idempotent replay. Demonstrations never derive Attempt, mastery, or progress state.

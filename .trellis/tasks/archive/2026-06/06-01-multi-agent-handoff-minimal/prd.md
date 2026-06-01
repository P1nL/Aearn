# Multi-agent handoff minimal

## Goal

Make router and handoff behavior minimally production-useful using stage, recent errors, learner profile, and tool context.

## Confirmed Facts

- `app/agents/router.py` currently routes by session stage and simple user-message keywords.
- `start_learning_message_generation()` already chooses an agent and handoff target list before constructing the SDK learning agent.
- Learning conversation context already has recent attempt and learner profile summary data.

## Requirements

- Make routing use stable context signals: stage, recent attempt/runtime errors, learner profile summary, and tool/exercise availability.
- Preserve existing default routing behavior when no extra signals exist.
- Avoid broad agent rewrites; keep a minimal rule-based router until the product needs a learned/planned router.
- Keep handoff target declarations safe and bounded.
- Cover signal-aware routing with tests.

## Acceptance Criteria

- [ ] Recent runtime errors can route a practice turn to diagnosis instead of generic teaching.
- [ ] Exercise/tool availability can route explicit practice/code requests to `exercise_coach`.
- [ ] Learner profile weak-point/error-pattern summaries can influence repeated-confusion routing.
- [ ] Existing review and stage-based routes remain compatible.
- [ ] Learning conversation passes relevant context signals into routing.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.

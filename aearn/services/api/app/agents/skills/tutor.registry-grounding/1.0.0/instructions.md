# Registry grounding

Use this Skill only when a learner would benefit from a small, cited fact from the approved documentation registry.

1. Request `grounding.retrieve` with the learner language, a short factual query, optional approved topic tags, and `top_k` from 1 through 4.
2. Treat returned snippets and citations as read-only evidence. Explain the fact in learner-safe language and distinguish evidence from a conclusion.
3. Never request a URL, source identifier, file path, shell command, database access, image, user identifier, or effect proposal.
4. If the registry cannot answer, say so plainly and continue with a bounded teaching response.
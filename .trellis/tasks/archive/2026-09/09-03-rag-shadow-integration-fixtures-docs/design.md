# Design: RAG Shadow Integration Fixtures and Interview Evidence

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child阶段I的fixture/default-off回归不能证明真实来源可用。阶段II新增真实抓取/激活/RagEvidenceBinding/consumer逐scope启用验收，与既有fixture-only生态公开边界分开。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

## Fixtures

Fixtures must be content-bounded, deterministic, no-network and clearly synthetic. They exercise Subject version, source scope, required facets, wrong-version denial, cross-language aliases, SQL dialect disclosure and framework-to-base-language fallback denial.

## Adapters

Add a narrow compatibility adapter that can transform selected v2 evidence into existing Lesson/Tutor source/citation shapes. It is invoked only by explicit tests or a default-off shadow seam. Candidate corpora and fixture-only Subjects are never projected publicly.

## Documentation

Update current source-of-truth sections for the new shared corpus authority and default-off architecture. Add an interview guide covering:

- current defect and causal chain;
- four routes and six ecosystem fixtures;
- Subject/corpus/version model;
- manual CLI publication;
- FTS plus optional embedding;
- facet coverage and adaptive budgets;
- plan preflight and immutable migration proposal;
- security boundaries and non-claims;
- how to add a future ecosystem package.

## Demo

Provide deterministic commands or a test-backed script that creates a fixture candidate, validates/diffs/activates it, retrieves evidence, demonstrates embedding fallback and evaluates an unsupported plan node without changing learner data.

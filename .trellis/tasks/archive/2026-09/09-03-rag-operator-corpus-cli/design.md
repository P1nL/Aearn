# Design: RAG Operator Corpus CLI

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child阶段I只交付手工CLI，不暗中加入scheduler。后续自动作业复用domain治理service，以独立v2授权驱动，不让模型执行任意CLI。旧manual路径和权限保持；新增worker属于阶段II实施包。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

## Service First

`corpus_service.py` owns transactions and lifecycle rules. `corpus_cli.py` only parses arguments, invokes one service operation, prints JSON and returns an exit code.

## Commands

- `status --subject`: active pointer, latest candidates, bounded health/count summary.
- `reindex --subject --subject-version --mode fixture|fetch`: snapshot registry and build a candidate.
- `validate --corpus-id --expected-generation`: run deterministic source/hash/version/facet/bounds/FTS validation.
- `diff --candidate-id`: compare candidate to the exact active corpus.
- `activate --candidate-id --expected-generation --summary-hash --idempotency-key`.
- `rollback --subject --target-corpus-id --expected-generation --idempotency-key`.
- `retire --corpus-id --idempotency-key`.

The CLI follows the existing Tutor cutover pattern. Output never includes raw fetched pages, secrets, arbitrary paths or provider bodies.

## Fixture Mode

Fixture mode resolves only registry-owned deterministic documents. It is the sole default-test and interview-demo mode. Fetch mode is explicit operator behavior and is not release evidence.

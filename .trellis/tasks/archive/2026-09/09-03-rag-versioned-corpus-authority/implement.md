# Implementation Plan: Versioned RAG Corpus Authority

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child仍拥有不可变corpus及active generation CAS。后续v2新增service principal/policy/真实provenance receipt与撤权检查，不能伪造operator receipt；手工/自动并发都走同一active指针，不建第二corpus。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

1. Start only after Child 01 contracts are committed.
2. Load database and backend quality specs.
3. Add the new schema fragment and manifest entry.
4. Add strict corpus contracts and repository mapping.
5. Implement candidate persistence, validation finalization, publication, active-pointer CAS, rollback and retirement.
6. Add immutable lifecycle and scope/hash database constraints/triggers.
7. Update schema manifest and shared-state/reset/export/cutover classification.
8. Add serial PostgreSQL tests for lifecycle, races, replay, bootstrap twice and legacy compatibility.
9. Run Ruff/Mypy/database tests, Trellis check, commit/archive and stop.

## Expected Write Scope

- `aearn/services/api/app/db/schema/260_rag_subject_corpus.sql`
- `aearn/services/api/app/db/schema/__init__.py`
- `aearn/services/api/app/services/grounding/corpus_contracts.py`
- `aearn/services/api/app/services/grounding/corpus_repository.py`
- focused database/grounding tests
- exact inventory files required by repository conventions

## Verification

```powershell
uv --directory .\aearn\services\api run pytest -q tests/database/test_db_bootstrap.py tests/database/test_schema_manifest.py tests/grounding/test_grounding_corpus_repository.py
uv --directory .\aearn\services\api run ruff check app/services/grounding/corpus_contracts.py app/services/grounding/corpus_repository.py tests/grounding/test_grounding_corpus_repository.py
uv --directory .\aearn\services\api run mypy app/services/grounding/corpus_contracts.py app/services/grounding/corpus_repository.py
```


## 2026-09-23 实施与验证隔离

- 用户明确同意提交上一轮四文件后继续；Subject 前置已提交 `3d54036`，child01 按本地非PR任务归档，未推送。
- 当前 child 已启动。旧设计预留的 210 前缀已被实际 manifest 占用，本轮使用 `260_rag_subject_corpus.sql`，只做增量不改旧 fragment 语义。
- 核心实现代理拥有 SQL260、manifest、corpus contracts/repository 及其测试；独立代理拥有共享 state 分类和 inventory 测试；主代理拥有文档、环境与最终集成验证。模型均 GPT-6-Sol。
- 临时库 `aearn_rag260_20260923_b43174d0d2` 从 template0 新建。既有 postgres 及学习验收库不 bootstrap、不 seed、不 reset。core 代理独占测试库直到明确释放；主代理后续串行验收。
- 每个数据库测试进程显式设置 DATABASE_URL、LLM_TYPE=disabled、PYTHON_DOTENV_DISABLED=1，并核对实际目标库。真实 provider、抓取、浏览器、公开 consumer、CLI 和自主激活均不在本child执行范围。
- 隔离记录：`output/rag-corpus-authority-20260923/runtime-isolation.json`。新实现与归档/日志记录未经本轮另行批准不自动提交/推送；上一轮四文件提交授权已执行完毕。


## 2026-09-23 工程检查完成（未提交）

- 七项 child 工程 AC 已勾选，当前状态继续 in_progress，待用户批准本轮提交后按流程归档。
- GPT-6-Sol implement/check 分别完成核心/分类实现与独立修复；主代理完成文档及最终全新库复验。
- 最终主代理：fresh bootstrap twice PASS；schema/corpus/inventory/cutover **37 passed**；legacy index/retrieval/citations/Lesson provenance **50 passed**；原离线Subject等回归 **48 passed**；Ruff、Mypy（4 source files）、lock、whitespace均通过。
- 检查修复封存快照换父逃逸、catch后半条发布状态、URL/JSON元数据约束、首次指针错误引用rollback回执，并补候选编辑/封存竞争测试。新约束及savepoint语义已同步既有database schema文档与backend database规范。
- 三个专用临时库均核对无活动连接后删除；未操作原有学习库业务数据、未启动真实provider/浏览器。
- 详细报告：`output/rag-corpus-authority-20260923/acceptance-status.md`；隔离/清理回执：同目录`runtime-isolation.json`。
- 未实现/未验收 child03 CLI及来源语义审计、后续RAG、自主题库、正式工件与完整小节。未跑全API/前端/负载/生产验收。

## 2026-09-23 用户批准提交与交接

已按用户确认的两批计划执行第1批：`eab2c58`（feat: add versioned RAG corpus authority），共10文件，未推送。工程证据与临时库清理已完成；此后本地非PR归档并记录journal，准备进入child03 operator CLI。此前“未提交”段落保留为当时状态，不代表当前仍未提交。

# 本地提交计划（待用户确认）

日期：2026-09-23。只做本地提交，不推送、不amend、不创建PR。

## 1. feat: add versioned RAG corpus authority

- `D:\works\Aearn\Aearn\.trellis\spec\backend\database-guidelines.md`
- `D:\works\Aearn\Aearn\aearn\services\api\app\db\schema\260_rag_subject_corpus.sql`
- `D:\works\Aearn\Aearn\aearn\services\api\app\db\schema\__init__.py`
- `D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\corpus_contracts.py`
- `D:\works\Aearn\Aearn\aearn\services\api\app\services\grounding\corpus_repository.py`
- `D:\works\Aearn\Aearn\aearn\services\api\app\services\tutor\cutover.py`
- `D:\works\Aearn\Aearn\aearn\services\api\tests\database\test_schema_manifest.py`
- `D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_grounding_corpus_repository.py`
- `D:\works\Aearn\Aearn\aearn\services\api\tests\grounding\test_grounding_corpus_inventory.py`
- `D:\works\Aearn\Aearn\docs\architecture\database-schema.md`

范围：本child实现/测试/规范/source-of-truth共10文件。37数据库定向、50旧读取兼容、48离线回归及Ruff/Mypy/lock已通过。

## 2. chore: archive RAG authority tasks and record verification

- `D:\works\Aearn\Aearn\.trellis\tasks\archive\2026-09\09-03-rag-subject-capability-taxonomy`（当前已生成的完整归档目录）
- `D:\works\Aearn\Aearn\.trellis\tasks\archive\2026-09\09-03-rag-versioned-corpus-authority`（第1批提交后才由task.py archive生成）
- `D:\works\Aearn\Aearn\.trellis\workspace\pinl\index.md`
- `D:\works\Aearn\Aearn\.trellis\workspace\pinl\journal-1.md`

只纳入这两个任务的归档和相应journal bookkeeping；生成后再核对实际Git路径，不全树git add。当前没有未识别的其他人dirty改动。

output下验收材料、运行隔离记录和本地未归档任务不强行加入Git；不提交任何.env或密钥。两批完成后按既有依赖进入09-03-rag-operator-corpus-cli，不扩展真实抓取/公开consumer。

# Tutor Skill Catalog EOL 回归持久修复

## Goal

恢复 Windows 工作树中 Tutor 对话输入能力，并通过版本化 `.gitattributes` 规则保证字节哈希 Skill bundle 在后续检出时保持其已发布的 LF/CRLF 原始字节约束。

## Background and Confirmed Facts

- 2026-09-03 的 Desktop `CLIENT_ERROR / Failed to fetch` 对应 `POST /api/tutor/conversations/{id}/inputs` 返回 500，不是 API 离线或 CORS 失败。
- 服务端异常为 `SkillCatalogValidationError: Skill instruction content hash does not match manifest`。
- `tutor.lesson-teaching@1.2.0` 的 `instructions.md` 与 `evals.json` 当前工作树为 CRLF；manifest 哈希精确匹配相同内容的 LF 字节版本。
- Git index 中两文件为 LF，当前 `core.autocrlf=true`；工作树 `.gitattributes` 已有 Skill 默认 `eol=lf` 及五个历史 CRLF 特例，但属性规则不会追溯重写已检出的 CRLF 文件。
- 仓库存在大量与本修复无关的并行修改，必须窄范围操作和提交。

## Requirements

- R1：只将 `tutor.lesson-teaching/1.2.0/instructions.md` 与 `evals.json` 重新物化为 manifest 期望的 LF 原始字节，不修改语义内容或 manifest。
- R2：保留并提交 `.gitattributes` 中 Skill bundle 默认 `text eol=lf` 规则及五个已确认的历史 CRLF 特例，使 Windows 后续检出不再破坏哈希。
- R3：禁止全仓库 renormalize、reset、clean 或批量 EOL 重写；不得覆盖其他未提交或并行修改。
- R4：验证必须直接编译已发布 Skill Catalog，并覆盖目标 Skill Catalog 测试。
- R5：验证期间不得自动重发 learner input 或触发付费模型请求。

## Acceptance Criteria

- [x] AC1：全量已发布 Skill bundle 原始字节检查输出 `HASH_MISMATCHES=0`。
- [x] AC2：`compile_published_skill_catalog()` 成功并报告非空 catalog。
- [x] AC3：`tests/tutor/test_tutor_skill_catalog.py` 全部通过。
- [x] AC4：API `/health` 继续返回 HTTP 200，现有 API/worker/Desktop 进程不因修复被破坏。
- [x] AC5：`git check-attr` 对两个 `1.2.0` 资源返回 `text=set, eol=lf`，五个历史资源仍为 `eol=crlf`。
- [x] AC6：最终暂存和提交仅包含本任务拥有的 `.gitattributes` 与 Trellis 任务归档文件；两个资源若仅恢复为 index 已有 LF 字节，不制造内容 diff。

## Out of Scope

- 修改 Skill 正文、manifest 哈希、Tutor 协议、Teaching Decision、DeepSeek/Codex 配置或模型路由。
- 全仓库 EOL 统一、重写历史 CRLF bundle、清理当前 dirty tree。
- 自动重试截图中的 `hi` 或进行真实 provider smoke。

## Open Questions

无阻塞问题；用户已于 2026-09-03 明确选择持久修复方案。

## Verification Evidence（2026-09-03）

- 全量扫描：`MANIFESTS_SCANNED=8`、`RESOURCES_SCANNED=16`、`HASH_MISMATCHES=0`。
- Catalog：`SKILL_CATALOG=PASS skills=8`。
- 目标测试：`13 passed`。
- Ruff：`All checks passed!`；Mypy：`Success: no issues found in 248 source files`。
- 两个 `1.2.0` 资源为 `i/lf w/lf attr/text eol=lf`；五个历史特例保持 `eol=crlf`。
- API health 返回 HTTP 200；未发送 learner input 或 provider/model 请求。
- 无 Skill 内容或 manifest diff；无 staged changes；无关 dirty-tree fingerprint 保持不变。

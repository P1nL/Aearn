# Local user data boundary 审核稿

## 目标

把 Aearn 的本地单机用户边界做完整：同一台 Windows 本机可以有多个本地用户画像，但路线、学习会话、练习记录、复习、笔记、设置、恢复状态不会互相混入。

## 范围

- 新增本地用户列表/切换、数据摘要、导出、reset、delete 的产品和 API 合同。
- 强化现有 `user_id` 边界，尤其是 `plan_id`、`note_id`、`session_id` 这类 ID-only 入口。
- 设置页隐私/记录面板展示当前本地用户、数据统计、导出、reset、delete、切换用户。
- `export` 输出 learner-safe JSON，不导出 hidden tests、solution references、raw prompts、provider payloads、API keys 或内部 runner 细节。

## 推荐语义

- `reset`：保留 `users` 画像和偏好设置，清空该用户的学习数据，然后把 desktop 的 `planId` 清掉并回到 onboarding。
- `delete`：不可逆移除或 soft-delete 该本地用户及其拥有的数据；如果删除的是当前用户，清空 `localStorage["aearn.bootstrap"]`。
- `export`：只导出学习者正常可见的数据和摘要，避免把 hidden tests 或内部提示词暴露给用户。
- 本任务不是公网认证、登录态、密码或 SaaS 多租户；它是 local-only 产品隔离和防误读边界。

## 关键设计取舍

- 优先复用当前 `localStorage["aearn.bootstrap"] = { userId, planId }`，围绕它补 switch/reset/delete 语义，不先重做整套前端身份系统。
- 后端新增本地用户数据管理服务，把 summary/export/reset/delete 的 SQL 顺序集中管理，避免在 route 里散落复杂查询。
- 现有 `idempotency_records` 需要用户级失效策略，否则 reset/delete 后旧幂等响应可能重新回放已删除的 plan/session/note 数据。
- 如果 hard delete 受 `ON DELETE RESTRICT` 约束风险太高，第一步可以用 soft-delete 加严格可见性过滤，但必须在文档中标注 physical delete 是否 deferred。

## 执行顺序

1. 先写双用户后端测试，暴露 plan/note/session/review 等跨用户读取或修改缺口。
2. 实现 `local_user_data_repository.py` 一类集中服务，负责 summary/export/reset/delete。
3. 补 schema/idempotency 支持和 API 路由。
4. 更新 desktop `api.ts`、`types.ts`、`useAppStore`、`useSettingsStore` 和 `SettingsPage.tsx`。
5. 更新 `docs/architecture/api-contract.md`、`docs/architecture/database-schema.md`、`docs/product/frontend-interaction-spec.md`、`docs/product/user-flows.md`。
6. 跑 focused backend tests、`ruff`、`mypy`、`pnpm --dir .\aearn desktop:check`、`task.py validate` 和 `git diff --check`。

## 验收标准

- 两个本地用户的数据不会在 route、dashboard、resume、review、notes、settings 中互相显示。
- reset 后同一用户仍存在，但 plan/session/review/note/attempt/conversation 学习数据清空，desktop 回 onboarding。
- delete 后正常 API 不能再读到该用户；如果它是当前用户，desktop bootstrap 被清空。
- export 不包含 hidden tests、solution references、raw prompts、provider payloads 或 secrets。
- Settings 页只有产品化数据管理入口，不暴露 `Attempt`、`ReviewState`、FSRS、`due_at` 或 runner 内部规则作为可配置项。

## 风险

- 删除顺序不对会触发 PostgreSQL FK 约束。
- 只 soft-delete 顶层对象可能留下 ID-only API 仍能读取的 session/attempt/note。
- 直接 dump exercises/test_cases 可能泄露 hidden tests。
- 前端切换用户如果不先清 store，会短暂显示上一个用户的学习状态。
- 现有测试可能需要补 `user_id`，因为当前部分 API 只按 id 查询。

## 回滚点

- schema 先做 additive change。
- reset/delete UI 必须等后端测试过再开放。
- 保留当前 bootstrap shape，减少前端迁移风险。
- hard delete 风险过高时可先落 soft-delete + visibility filters，但要明确后续补 physical delete。

## 待用户确认

推荐按上述语义继续：`reset` 保留用户画像和偏好，只清学习数据；`delete` 删除整个本地用户及其拥有数据；`export` 保持 learner-safe redaction。
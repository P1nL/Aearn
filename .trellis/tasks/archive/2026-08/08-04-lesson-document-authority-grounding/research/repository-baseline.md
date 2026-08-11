# LessonDocument 仓库基线

## 已完成的依赖

- 归档任务 `08-04-learning-track-plan-mastery-domain` 已交付 `tutor_learning_tracks`、active plan、stable `knowledge_key`、progress/mastery、conversation/run learning scope 与 `lesson_teaching` task kind。
- 归档任务 `08-04-learning-home-plan-builder` 已交付 Learning Home、planning session、typed plan draft 和 server-authoritative track card；`App.tsx` 的 `continue_learning` 当前进入 `downstream_not_ready`。
- 父任务明确要求标准/个性化/frozen LessonDocument、来源快照、注册 block 与质量门；练习 Gate、Review、模型代码审核和完整三栏工作区属于后续 child。

## 当前 LearningTrack 接缝

- `aearn/services/api/app/services/learning/contracts.py` 已定义 `LearningTaskKind.LESSON_TEACHING`，`LearningScope` 的 track scope 可携带 `knowledge_key`。
- `track_repository.py` 已保证 run scope 的 track/key 属于当前用户 active plan；`TutorLearningContextAdapter` 可投影 language、goal、active revision、当前 node progress/mastery，但尚无 Lesson identity。
- `/api/learning-tracks` 已提供 list/detail/roadmap/revision API；track list 返回 server-owned `current_knowledge_key`，前端不得猜测首节点。
- `tutor_track_node_progress` 的 `available | in_progress | completed | review_due | diagnostic_skipped` 可读取课程，`locked` 必须拒绝 prepare/start。

## 当前 Grounding 接缝

- `grounding_sources.py` 提供 source ID、language、display/provider、trust tier、allowlisted domain、seed URL、content type 与 topic tags。
- `GroundingDocsFetcher` 只抓 registered/allowlisted URL；`GroundingFetchDocument` 有 raw document SHA-256。
- `clean_and_chunk_document()` 产出 `GroundingChunk`，当前保留 source/language/title/section/URL/type/trust/`fetched_at`/chunk hash/text/tags，但没有显式 source version 和 raw document hash。
- `grounding_chunks` 是可 reindex/replace 的检索索引，不适合直接作为 frozen Lesson 引用 authority；Lesson 必须复制不可变 source snapshot。
- `build_official_docs_grounding_context()` 与 registry-only `grounding.retrieve` 已证明 persisted index、citation metadata、allowlist 和 safe bounded projection；Lesson authoring应复用这些源合同，不开放 arbitrary URL。

## 当前 Harness / Provider 边界

- `CatalogCapabilityGateway` 的通用 payload 受 `MAX_TUTOR_PAYLOAD_FIELDS` 与单值上限约束；完整 Lesson blocks 不应塞入通用 capability envelope，也不应扩大 plan-drafting 已冻结限制。
- current runtime 的 provider 调用遵守 primary-only、strict output、无 fallback、raw body/reasoning 不持久化；Lesson authoring port 应复用配置与 usage normalization，但作为 server-owned artifact workflow单独持久化 lifecycle。
- provider 调用不能在持有长 PostgreSQL transaction 或 track lock 时执行；post-commit dispatcher + durable lease符合现有 interactive dispatch 恢复模式。

## 当前 Desktop 接缝

- `App.tsx` 的 verified shell 内部 surface 为 `learning_home | track_planner | downstream_not_ready`。
- `LearningHomePage` 的 track card 只消费 server projection，continue/review 产生稳定 intent。
- `types.ts` / `api.ts` 已使用严格 union与 unknown boundary validators；Lesson必须延续该模式。
- 当前没有前端测试 runner。仓库规范要求对用户可见改动只在 `http://127.0.0.1:1420` 真实浏览器验证，且用户明确要求不运行 Desktop build/typecheck。

## 数据生命周期接缝

- `local_user_data_repository.py` 已将 LearningTrack/planning 纳入 summary/export/reset/delete，并使用 transaction-local `aearn.learning_track_purge_user_id` 清理 immutable rows。
- `services/tutor/cutover.py` 的 `_TARGET_COUNT_SQL` 将 user-owned Tutor roots视为 target contamination；新 personalized Lesson/assignment/authoring root必须加入，shared standard docs不能按某个用户删除。
- `test_db_bootstrap.py` 目前的通用 `TARGET_TUTOR_TABLES` 未包含后续 LearningTrack tables；Lesson实现应在自己的 schema/repository tests明确冻结新表/trigger/index，必要时同步通用 bootstrap inventory。

## 规划结论

1. 标准 LessonDocument 使用共享 immutable row；personalized document与 assignment严格 user/track/key scoped。
2. Grounding index只作为输入；发布时复制 source/version/hash/excerpt snapshot，保证 reindex 后可重放。
3. 完整 Lesson authoring不进入通用 Tutor capability payload；使用 durable post-commit authoring run、strict injected author port与 safe attempt receipt。
4. 首页 continue进入单页 Lesson阅读面；完整三栏、右侧 Tutor与结构化选区后置，但 renderer必须可复用。
5. `exercise_gate` 只冻结公开 slot contract，后续 child再绑定 exercise/Attempt/rubric/execution/unlock。
6. 前端验收只用网页端真实浏览器；后端使用 fake author、fixture grounding和真实 PostgreSQL contract测试，不调用真实 provider。

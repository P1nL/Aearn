# 领域基础实现证据

- 父级仓库基线：`.trellis/tasks/08-04-programming-language-learning-agent-product/research/repository-baseline.md`。
- 当前 `tutor_plan_revisions` / `tutor_active_plans` 是 user-level active plan，见 `aearn/services/api/app/db/schema.sql:1593-1630`，不能直接表达多个 LearningTrack。
- 当前旧课程表仍在 schema，但 active `main.py` 未注册旧 plans/learning/review 路由；新实现必须保持隔离。
- 当前 ordinary input 继续创建 fresh finite TurnRun，scope 必须作为新增不可变 snapshot，而不是替换 run lifecycle。
- 当前 language capability registry 与 executor runtime catalog 已存在；`image-locks.json` 为空，因此 public resolver 必须 fail closed。

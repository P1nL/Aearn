# Codex Sidecar 集成 QA 与文档

## 目标

在 Child 1-5 完成后，对 Codex Sidecar 的协议、领域工具、持久化、公开投影、受控切换和回滚执行全链路验收，并把最终支持矩阵、运维边界、失败语义和非承诺项同步到 Aearn source-of-truth 文档。真实 provider smoke、安装和生产动作仍需单独授权。

## 依赖

- 父任务：`08-17-codex-runtime-sidecar-integration`。
- 前置任务：Child 1-5 全部完成并归档，验证证据可读取。

## 需求

### R1：自动化失败矩阵

覆盖 executable/version、auth、capability、startup、protocol、dynamic tool schema、repair、awaiting user、conflict、policy、stale revision、lease loss、interrupt、timeout、child crash、DB冲突、duplicate replay、unsafe final 和 shutdown。

### R2：双 Runtime 回归

- feature off 的 Harness 全量关键路径不回归。
- feature on 的新 plan-drafting Codex vertical slice完成事实收集、草案生成、一次repair和可见final outcome。
- existing/其他 scope仍走Harness，不能出现双写、跨 Runtime fallback或 public DTO漂移。

### R3：真实 Smoke 与回滚演练

- 真实 `deepseek-v4-flash` Responses调用默认 opt-in，执行前展示模型、预计调用范围、隔离Home、日志边界并获得明确批准。
- smoke只记录版本、状态、timing、安全rubric与哈希，不记录完整prompt/response或credential。
- 演练关闭admission、interrupt/完成active run、停止worker、重启Harness和保留evidence。

### R4：Source of Truth 文档

- 更新 `docs/README.md` 索引及对应 runtime、API、DB、setup、user flow、acceptance/release evidence文档。
- 明确安装/版本/auth/preflight、worker lifecycle、feature policy、failure codes、observability、数据保留与回滚。
- 明确非声明：不等于生产批准、不捆绑Codex、不代表所有Tutor已切换、不公开reasoning/raw tool数据。

## 范围外

- 未经批准的真实付费调用、Codex安装/升级、生产部署和用户流量切换。
- 扩展到proactive、Lesson、Exercise、Review或远程WebSocket。
- 修改Codex源码或发布分发包。

## 验收标准

- [ ] 自动化失败矩阵全部通过，且每类失败有独立稳定 outcome/code。
- [ ] Harness feature-off回归、Codex plan-drafting vertical slice和scope isolation通过。
- [ ] repairable错误可在同Turn完成修复；fatal/interrupt/crash均有可见终态，不出现空白Turn。
- [ ] DB/API/SSE/Desktop/日志扫描未发现raw reasoning、prompt、tool arguments/results、credential、command或非必要path。
- [ ] rollback演练证明关闭新admission后Harness可继续服务，历史Codex evidence保留。
- [ ] 真实smoke仅在单独批准后执行；未批准时明确记录为未执行，不伪造通过。
- [ ] 所有相关source-of-truth文档与实际代码、配置、测试命令一致。
- [ ] 父任务跨任务验收清单完成，Trellis validate与 `git diff --check`通过。

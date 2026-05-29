# 执行计划 — 动态学习路线生成

## 前置条件

- [x] PRD 完成
- [x] Design 完成
- [x] 确认 web search API 选型：当前实现使用 Exa，配置键为 `EXA_API_KEY`
- [x] 明确范围边界：动态生成不改变 `PlanDraft`、`Language`、数据库约束、catalog 或 runtime boundary；新增语言公开支持单独建后续任务

## 实施步骤

### Phase 1: Web 工具层

- [x] 1.1 新建 `aearn/services/api/app/agents/tools_web.py`
  - 实现 `web_search` function_tool（调用 exa API）
  - 实现 `fetch_doc_toc` function_tool（HTTP GET + BeautifulSoup 提取 h1-h3）
  - 添加超时控制（单次请求 5s）
  - 添加返回长度截断（≤ 2000 字符）

- [x] 1.2 `Settings` 新增配置项
  - `exa_api_key: str | None = None`
  - `plan_generation_enabled: bool = True`

### Phase 2: Agent 核心

- [x] 2.1 新建 `aearn/services/api/app/agents/plan_generation_agent.py`
  - `PlanGenerationContext` dataclass
  - `AUTHORITATIVE_DOCS` 映射表
  - System prompt（结构约束 + 输出 schema + 中文要求）
  - `AgentsSDKPlanGenerationClient` 实现
  - `build_plan_generation_context()` 构建函数
  - `build_sdk_plan_generation_response()` 编排函数
  - `_validate_dynamic_plan_response()` schema 级验证
  - `_parse_dynamic_modules()` JSON → list[DraftModule] 转换

- [x] 2.2 验证逻辑
  - modules 数组非空且 4-8 个
  - 每个 module 必填字段完整
  - temp_id 格式正则校验
  - title/description 包含 CJK 字符
  - knowledge_points 2-4 个/module
  - `assert_safe_teaching_output` 安全检查

### Phase 3: 路由集成

- [x] 3.1 修改 `aearn/services/api/app/routes/plans.py`
  - 在 `generate_plan` 中调用动态生成
  - 成功时使用动态结果，失败时 fallback 到静态模板
  - `source` 字段标记为 `"agent_generated"`
  - `source_attribution` 追加参考 URL

- [x] 3.2 Fallback 逻辑
  - 捕获 `SAFE_GENERATION_EXCEPTIONS` + `TimeoutError`
  - 重试 1 次（附加错误提示）
  - 最终失败回退到 `COURSE_TEMPLATES`
  - 日志记录 fallback 事件

### Phase 4: 测试

- [x] 4.1 单元测试 `tests/test_plan_generation_agent.py`
  - Mock web_search / fetch_doc_toc 返回
  - 验证正常生成流程
  - 验证 fallback 流程（LLM 返回无效 JSON）
  - 验证 schema 验证拒绝不合格输出
  - 验证中文内容检查

- [x] 4.2 集成测试
  - 端到端调用（需要 API key，CI 中 skip）
  - 验证生成延迟 ≤ 15s

### Phase 5: 清理

- [x] 5.1 确认 `__init__.py` 无需新增导出（当前 agents 通过模块路径直接导入）
- [x] 5.2 确认现有测试不受影响（`pytest aearn/services/api/tests/`）
- [x] 5.3 同步 source-of-truth docs：`docs/README.md`、`docs/product/user-flows.md`、`docs/architecture/api-contract.md`、`docs/qa/acceptance-test-plan.md`、`docs/setup/development-environment.md`、`docs/plans/learning-agent-implementation-plan.md`

## 验证命令

```bash
# 语法检查
cd aearn/services/api && python -c "from app.agents.plan_generation_agent import build_sdk_plan_generation_response; print('OK')"

# 单元测试
cd aearn/services/api && python -m pytest tests/test_plan_generation_agent.py -v

# 全量测试回归
cd aearn/services/api && python -m pytest tests/ -v --timeout=30

# 类型检查（如果配置了 mypy/pyright）
cd aearn/services/api && python -m mypy app/agents/plan_generation_agent.py --ignore-missing-imports
```

## 回滚点

- Phase 1-2 完成后：新文件可直接删除，不影响现有功能
- Phase 3 完成后：将 `plan_generation_enabled` 设为 False 即可回退到纯模板模式
- 任何阶段：`COURSE_TEMPLATES` 始终保留，fallback 路径始终可用

# 技术设计 — 动态学习路线生成

## 架构概览

```
PlanGenerateRequest
        │
        ▼
┌─────────────────────────┐
│  plan_generation_agent  │  (新建)
│  ┌───────────────────┐  │
│  │  system prompt    │  │  ← 结构约束 + 语言映射 + 用户上下文
│  │  + web_search     │  │  ← 新增 @function_tool
│  │  + fetch_doc_toc  │  │  ← 新增 @function_tool
│  └───────────────────┘  │
└────────────┬────────────┘
             │ structured JSON output
             ▼
┌─────────────────────────┐
│  validate & parse       │  → PlanDraft (Pydantic)
└────────────┬────────────┘
             │
     ┌───────┴───────┐
     │ success       │ failure (2 retries)
     ▼               ▼
  PlanDraft     COURSE_TEMPLATES fallback
```

## 核心组件

### 1. `plan_generation_agent.py` (新文件)

遵循 `onboarding_plan_agent.py` 的模式：

- `PlanGenerationContext` dataclass：封装 language、target_level、goal_text、time_budget、profession、materials
- `AgentsSDKPlanGenerationClient`：实现 `complete_json` 协议
- `build_plan_generation_context(payload, user, course) -> PlanGenerationContext`
- `build_sdk_plan_generation_response(context, *, settings, client) -> dict | None`

关键差异：
- `tools=[web_search_tool, fetch_doc_toc_tool]`（首次引入外部网络工具）
- `max_turns=6`（允许多轮 tool call：search → fetch → generate）
- 输出验证不再约束为模板子集，改为 schema 级验证

### 2. Web Search Tool (`agents/tools_web.py` 新文件)

```python
@function_tool
async def web_search(query: str, max_results: int = 5) -> str:
    """搜索权威编程文档。返回标题和 URL 列表。"""
    # 使用 Exa API（通过 settings 配置）
    ...
```

```python
@function_tool
async def fetch_doc_toc(url: str) -> str:
    """获取文档页面的目录结构（标题层级）。"""
    # HTTP GET + HTML 解析提取 h1-h3 结构
    # 限制返回长度 ≤ 2000 字符
    ...
```

### 3. 权威文档映射表 (`AUTHORITATIVE_DOCS`)

```python
AUTHORITATIVE_DOCS: dict[str, list[str]] = {
    "python": ["https://docs.python.org/3/tutorial/"],
    "javascript": ["https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide"],
    "html_css": [
        "https://developer.mozilla.org/en-US/docs/Learn/HTML",
        "https://developer.mozilla.org/en-US/docs/Learn/CSS",
    ],
    "typescript": ["https://www.typescriptlang.org/docs/handbook/"],
    "rust": ["https://doc.rust-lang.org/book/"],
    "go": ["https://go.dev/tour/", "https://go.dev/doc/effective_go"],
    "java": ["https://docs.oracle.com/javase/tutorial/"],
    "cpp": ["https://en.cppreference.com/w/cpp/language"],
}
```

Agent 优先 `fetch_doc_toc` 映射表中的 URL；映射表中没有的语言则先 `web_search` 发现文档。

### 4. System Prompt 设计

核心指令：
1. 你是一个编程学习路线规划师，为中文用户生成学习模块
2. 参考权威文档的目录结构确定模块顺序和覆盖范围
3. 根据用户水平裁剪深度，根据目标裁剪侧重
4. 输出必须为严格 JSON，符合给定 schema
5. title 和 description 必须为中文
6. 每个路线 4-8 个模块，每个模块 2-4 个知识点

输出 schema（嵌入 prompt）：
```json
{
  "modules": [
    {
      "temp_id": "mod_draft_{language}_{slug}",
      "title": "中文标题",
      "description": "中文描述",
      "order_index": 0,
      "is_skippable": false,
      "estimated_sessions": 3,
      "knowledge_points": [
        {
          "temp_id": "kp_draft_{language}_{slug}",
          "title": "中文标题",
          "description": "中文描述",
          "skill_tags": ["tag1", "tag2"],
          "exercise_refs": []
        }
      ]
    }
  ],
  "source_urls": ["https://..."],
  "generation_notes": "简要说明参考了哪些文档章节"
}
```

### 5. 路由层集成

修改 `routes/plans.py` 的 `generate_plan`：

```python
# 现有流程
deterministic_plan_draft = build_plan_draft(payload, user, course)

# 新增：尝试动态生成
dynamic_response = await build_sdk_plan_generation_response(
    build_plan_generation_context(payload, user, course)
)

if dynamic_response is not None:
    plan_draft = _parse_dynamic_plan_draft(dynamic_response, payload, user, course)
    # 保留 deterministic 的 runtime_boundary（服务端控制）
    plan_draft = plan_draft.model_copy(update={
        "runtime_boundary": deterministic_plan_draft.runtime_boundary,
        "draft_id": deterministic_plan_draft.draft_id,
    })
else:
    plan_draft = deterministic_plan_draft  # fallback
```

## 数据流

1. 用户提交 `PlanGenerateRequest`
2. 路由构建 `PlanGenerationContext`
3. Agent 收到 context，决定是否需要 web search
   - 映射表有 URL → 直接 `fetch_doc_toc`
   - 映射表无 URL → `web_search` 找文档 → `fetch_doc_toc`
4. Agent 基于文档目录 + 用户上下文生成 JSON
5. 验证 JSON 符合 schema → 解析为 `list[DraftModule]`
6. 组装 `PlanDraft`（服务端填充 draft_id、user_id、runtime_boundary 等）
7. 失败时回退到 `COURSE_TEMPLATES`

## 验证策略

与 `onboarding_plan_agent` 的严格模板匹配不同，动态生成采用 schema 级验证：

1. JSON 结构验证：modules 数组非空，每个 module 有必填字段
2. temp_id 格式验证：正则 `^mod_draft_[a-z_]+_[a-z_]+$` / `^kp_draft_[a-z_]+_[a-z_]+$`
3. 中文内容验证：title/description 包含至少一个 CJK 字符
4. 数量边界：4-8 modules，每 module 2-4 knowledge_points
5. 安全检查：`assert_safe_teaching_output` 对所有文本字段

## Fallback 策略

```
尝试动态生成（max_turns=6, timeout=20s）
    ├─ 成功 → 使用动态结果
    ├─ JSON 解析失败 → 重试 1 次
    │       ├─ 成功 → 使用动态结果
    │       └─ 失败 → fallback
    ├─ Schema 验证失败 → 重试 1 次（附加错误提示）
    │       ├─ 成功 → 使用动态结果
    │       └─ 失败 → fallback
    ├─ 网络超时 → fallback
    └─ LLM 异常 → fallback

fallback = COURSE_TEMPLATES[language]（如果存在）
         | 返回 422 PLAN_DRAFT_INVALID（如果语言无模板）
```

## 配置

`Settings` 新增：
- `exa_api_key: str | None` — Exa API key
- `plan_generation_enabled: bool = True` — 总开关，关闭时直接走模板

## 兼容性

- `PlanDraft` 模型不变
- 下游（`confirm_plan`、前端渲染）无需任何修改
- `source_attribution` 字段自然扩展（追加 URL）
- `DraftModule.source` 字段设为 `"agent_generated"`（已有枚举值）
- `DraftKnowledgePoint.source` 同上
- 当前公开语言范围仍由 `Language`、数据库 CHECK、课程 catalog 和 runtime boundary 共同拥有。`AUTHORITATIVE_DOCS` 可以先包含 TypeScript、Rust、Go 等后续目标 URL，但只有完成 schema/catalog/runtime 扩展后才能作为可确认计划公开。

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| Web search 延迟不可控 | 20s 总超时 + fallback |
| LLM 输出格式漂移 | 严格 schema + 重试 + fallback |
| 权威文档 URL 失效 | fetch_doc_toc 失败时 agent 自动 web_search |
| 生成内容质量不稳定 | 安全检查 + 数量边界 + 中文验证 |
| API key 未配置 | `plan_generation_enabled` 开关 + 优雅降级 |

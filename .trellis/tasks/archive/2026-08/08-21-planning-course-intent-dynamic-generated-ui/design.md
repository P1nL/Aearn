# 技术设计

## 1. Schema

### `tutor_learning_intents`

- `intent_key`：closed stable key。
- `display_name`、`state=active|planned|retired`、`policy_version`、timestamps。
- 首轮 keys：frontend、backend、web、data_analysis、data_science、database、automation、general_programming、mobile、systems。

### `language_course_intent_tags`

- `(course_id, intent_key)` 主键。
- `relevance_rank 0..100`、`is_primary`、`policy_version`、created_at。
- FK 到 `language_courses` 和 taxonomy；禁止删除 active lineage，local purge 按现有开发数据策略处理。

Bootstrap 以稳定 slug 只做一次性 backfill；运行期绝不读取 slug/title 判定方向。

## 2. Resolver

```python
PlanningLanguageIntent(
    policy_version: str,
    explicit_language_ids: tuple[str, ...],
    intent_tags: tuple[str, ...],
    candidate_course_ids: tuple[str, ...],
    resolution: Literal["auto_confirm", "shortlist", "full_catalog", "conflict", "unsupported"],
    reason_code: str,
)
```

步骤：

1. Unicode/case/word-boundary 规范化 learner text。
2. 使用 `LanguageCapability.aliases` 与 public course map 解析明确语言。
3. 使用高精度方向词典解析 closed intent tags。
4. 如启用模型 hint，只接受 closed tag schema；服务端重新验证。
5. 查询 active course/tag join，按 explicit set、intent set、冲突矩阵和 rank 生成 course IDs。
6. 唯一明确语言自动 confirmed；其他结果只进入 typed presentation。

## 3. Fact 写入

在 plan_drafting fresh input 已有 run/message/input revision 后执行 resolver。`auto_confirm` 时调用现有 planning fact append authority：

```text
field_key=language_id
state=confirmed
source_kind=deterministic_input
source_message_id/source_run_id/source_input_revision=current evidence
policy_version=planning-language-intent-v1
```

幂等键继续使用 session/field/run/input/value hash；重复同值不增加 revision。已 confirmed 字段不自动覆盖。

## 4. Presentation

`build_planning_question_presentation` 接受 server-owned intent context：

```text
selection_scope = explicit_shortlist | intent_shortlist | conflict_shortlist | full_catalog
selection_reason_code = allowlisted code
intent_policy_version
recommended = null | exact candidate
options = persisted active course rows
```

用户公共 DTO 不含 intent evidence、正则、模型理由或内部 course IDs；value 继续使用 canonical public language/course value，label 来自持久 presentation。

## 5. Desktop

- `recommended` 变为 nullable。
- Language single-select 初始 selection 为空；提交按钮在 selection 为空时 disabled。
- 非语言问题保持现有 recommended 行为。
- snapshot/request refresh 以 durable presentation 为 authority，不重新请求 catalog 决定当前 options。

## 6. 安全与冲突

- 模型 hint 不能自动确认语言。
- 多语言 + direction 使用交集；交集为空进入 conflict shortlist，不静默扩大到全部目录。
- 明确 unsupported language 返回受控替代/不可用状态，不能静默换成首项。
- 所有查询 owner/session scoped；taxonomy 本身是公共产品 metadata，不含用户数据。

## 7. 迁移与回滚

- Additive schema + idempotent seed。
- Feature flag off 时使用 full active catalog，但语言 UI 仍无默认选择。
- 回滚不删除 metadata、facts 或 durable requests。

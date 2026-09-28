# P3 真实 dispatcher PostgreSQL 阻塞诊断（2026-09-27）

## 当前状态

- 执行权已归还主会话；本代理无正在运行的PG测试。第二次单用例运行在2026-09-27被用户要求checkpoint时通过Ctrl+C终止，**没有得到修复后结果**。两个dispatcher用例均不得报passed。
- 已验证隔离库为 `aearn_rag260_c_d_integration_20260927_1`（localhost:55437、非默认5432），`SELECT current_database()`匹配D前缀。仅执行本任务单用例，没有碰业务库、真实provider或外网。第一次单用例实际失败：`tutor_runtime_failed`、首run capability_count=0；临时测试侧monkeypatch在`TutorRunLoop._terminal`的异常处理栈取到原始异常，之后已从测试文件移除，不修改生产safe mapping。

## 第一个具体异常与已改测试替身

- 异常：`LearningPlanDraftCapabilityInput`三个字段 `profile_json`, `module_1`, `module_2` 均为 `Input should be a valid string`，实际input_type=dict。
- 根因：`tests/learning/test_rag_d_planning_consumer.py` 的 `FeedbackProvider.decide` 原将JSON文本直接作为`TutorPayloadField.value`；现行真实协议 `app/agents/harness/contracts.py:1441-1451`逐字段`json.loads`，使JSON对象文本解码为dict，而能力输入定义 `app/agents/harness/capabilities.py:125-137` 要求的是紧凑JSON **字符串**。错误经`app/services/tutor/run_loop.py:402-410`正常安全映射，非D权限失败。
- 已在测试侧修复：`TutorPayloadField(k, json.dumps(v, ensure_ascii=False, separators=(",", ":")))`；修订后的profile本身也用紧凑JSON序列化。离线测得双层编码后的SQL修订profile长度347，小于既有360上限。之前 `mixed_skill_selection_action`已按现行协议拆为三个model decision：只选skill→只调用capability→终结；未修改gate、预算或生产错误映射。

## 主会话复现与验收

主会话设置 `PYTHON_DOTENV_DISABLED=1`、`LLM_TYPE=disabled`，将 `DATABASE_URL` 和 `AEARN_RAG_D_TEST_DATABASE_URL` 设为同一已批准的 localhost:55437 D隔离库DSN；先用psycopg执行`SELECT current_database()`并核对 `aearn_rag260_c_d_*`，然后从仓库根运行：

```powershell
uv --directory .\aearn\services\api run python -m pytest -x -q tests/learning/test_rag_d_planning_consumer.py
```

两条用例都要到dispatcher→context→gateway→capability→实际plan repo；第二条使用P2 `setup_ready` 的唯一synthetic registered URL及真实C facade，同连接current授权验证，非真实来源验收。该C seed提交到可丢弃隔离库以供dispatcher另连接读取；每次随机URL/policy/dispatch避免重跑冲突，但不自动清理历史行。主会话fresh DB独立复验后再判定passed/failed。

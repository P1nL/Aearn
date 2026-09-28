# Research: 真实规划 Provider 单次请求预检

- Query: 既有规划 provider/client 的安全配置、JSON 修订调用、输入输出上限、usage、超时/取消，以及一次有界真实调用草图。
- Scope: internal
- Date: 2026-09-27

## Findings

### Files found and code patterns

- `docs/setup/project-external-resource-policy.md:3-13,15-24,28-46`：持续开发授权；累计 CNY300、240 参考线由用户监控；免费 Tavily 额耗尽后 existing_only；无自动硬封顶；停止后不新增付费调用；不授权生产/公开消费者。`prd.md:55-59` 同步了人工监控变更。
- `aearn/services/api/app/core/config.py:30-31,75-81,150,475-583,586-588`：模块加载时从 `aearn/.env` 载入环境；`get_settings()` 缓存 `Settings()`；`llm_provider_type`、`llm_model`、`llm_base_url`、`llm_api_key` 选择配置的 openai/deepseek，且 `llm_configuration_status` 判定配置是否完整。**仅打印** provider/type、model、`urlsplit(base_url).hostname`、`bool(key)`，不要 `model_dump`、环境变量清单、完整 URL、key 或错误明文；本侧车未读取运行时 `.env` 或秘钥，也未验证当前具体 provider/model/host。
- `aearn/services/api/app/services/tutor/interactive.py:1031-1065,1077-1088,1123-1127,1191-1192`：正常规划通过 `PlanDraftingProviderGateway` 包装 `PrimaryTutorProviderGateway`，并非一个独立“规划模型账号”。后者 `provider_gateway.py:145-171,173-188,245-268,546-556` 经既有 `OpenAICompatibleClient(settings)` 调 `complete_json(messages, temperature=None, max_tokens=settings.tutor_decision_max_output_tokens, timeout_seconds=..., output_schema=tutor_provider_output_schema(), schema_name=...)`；Gateway 包含完整 Tutor run/context、可重试决策与服务端验证，不宜用孤立临时输入假冒 D 运行。
- `aearn/services/api/app/services/llm/llm_client.py:79-98,134-144,160-239`：`OpenAICompatibleClient.complete_json(...) -> LLMJsonResponse(content: dict, model: str, usage: LLMUsage|None, response_diagnostics: ...|None)` 是既有**单次同步 JSON 调用接口**；按精确 provider/model 选 Responses / DeepSeek Chat Completions / DeepSeek Flash Responses。DeepSeek Chat 采用 JSON object，Responses 在传 schema 时用 strict json_schema（Flash 取决于开关），最终需本地校验目标 DTO。`llm_client.py:357-435,486-548`：Responses **调用方非流式拿 JSON 对象，但线协议内部是 stream=True 的 SSE**；Chat 是普通 JSON HTTP 请求。不要宣称所有协议网络非流式。
- `aearn/services/api/app/services/learning/plan_tools.py:116-214`：真实计划草案结构 `LearningPlanDraftToolInput(schema_version="aearn-learning-plan-tools-v1", modules[2..8], nodes[1..8])`，每节点有 stable_key/title/description/is_core/prerequisites/required_capabilities/catalog_knowledge_key，验证唯一 key 和前置 DAG。草图只允许改描述，不允许删改模块/节点稳定身份、标题、核心性、前置、能力和 catalog key；经 `model_validate_json` 验证（`.trellis/spec/backend/grounding-plan-material-consumption.md:50-54`）。这是受控模型建议，不是正式反馈关联、selection 或 binding authority。
- `aearn/services/api/app/core/config.py:9-27,196-210,226-245,518-532`：Flash 输入默认 128Ki tokens、输出模型上限默认 60Ki、决策默认 16,384（可配置且有上界），普通 Tutor 决策默认 1,200；草图显式 `max_tokens=800`。`llm_client.py:642-683` 只对精确 Flash 实施近似序列化输入限制和模型输出上限；其他模型输入硬上限在此客户端未见，不应假定。草图另限制摘录 UTF-8 2,000 bytes、消息 UTF-8 6,000 bytes。
- `aearn/services/api/app/core/config.py:150` + `llm_client.py:636-639,553-612,725-777,29-37`：默认 socket timeout 20 秒；`timeout_seconds` 取 `max(configured, requested)`，不能靠传入较小值缩短配置；无公开取消 handle，不能承诺中途撤销已发请求。底层对 408/429/5xx/传输异常最多自动 3 次（失败仍可能计费）。草图仅在临时独立进程将模块常量 `LLM_PROVIDER_RETRY_ATTEMPTS=1`，**不改产品代码**，使一次 `complete_json` 最多发一次网络请求；单个连接的 socket timeout 不等于绝对 wall-clock 截止。
- `aearn/services/api/app/services/llm/contracts.py:8-61,73-100` + `llm_client.py:1206-1260`：usage 标准字段 `input_tokens, cached_input_tokens, output_tokens, total_tokens, reasoning_tokens`；缺失可能为 None，不能当零。diagnostics 为 allowlisted 状态、incomplete reason、requested max output、reasoning effort、visible chars。不可将 token usage 换算成准确人民币余额。
- `aearn/services/api/app/services/tutor/latest_input_smoke.py:143-179`：已有真实 provider smoke，但它跑完整 Tutor Gateway 用例、多次请求且输出公开文本；不适合本次单次、合成草案隔离预检。
- `aearn/services/api/pyproject.toml:5,14-15`：Python >=3.11,<3.13，使用 Pydantic 和 python-dotenv；不需要新增 OpenAI SDK/账号。

### Main 可运行的最小草图（仅 MAIN 执行；本侧车未执行）

将下面内容由 MAIN 保存在**任务研究目录外的临时脚本**，在 `aearn/services/api` 当前目录运行 `python <临时脚本.py> <已获准公开来源摘录UTF-8文件>`。文件只含经 MAIN 确认可发送的公开摘录，勿用真实 learner 数据。脚本不连 DB、不写文件、不发布；输出仅打印合成草案的两个修订描述（各不超过300字符）、校验布尔值、usage/diagnostics 和脱敏配置元数据。若配置的 `LLM_TIMEOUT_SECONDS` 超过30秒，则预检拒绝启动，而非误以为传入30能缩短它。

```python
import json
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.services.llm import llm_client
from app.services.learning.plan_tools import LearningPlanDraftToolInput

settings = get_settings()  # config.py 自行加载 aearn/.env；不要打印 Settings/环境
metadata = {
    "provider": settings.llm_provider_type,
    "model": settings.llm_model,
    "base_host": urlsplit(settings.llm_base_url or "").hostname,
    "key_present": bool(settings.llm_api_key),
    "configuration_status": settings.llm_configuration_status,
}
print(json.dumps({"preflight": metadata}, ensure_ascii=False))
if settings.llm_configuration_status != "configured":
    raise SystemExit("configured normal planning provider required")
if not (0 < settings.llm_timeout_seconds <= 30):
    raise SystemExit("configured socket timeout is outside this preflight bound")
raw = Path(sys.argv[1]).read_bytes()
if not (1 <= len(raw) <= 2000):
    raise SystemExit("public excerpt must be 1..2000 UTF-8 bytes")
excerpt = raw.decode("utf-8")
# Two-module fixture is the existing plan-tool DTO minimum. No real user/handle/DB IDs.
draft_json = json.dumps({
    "schema_version": "aearn-learning-plan-tools-v1",
    "modules": [
        {"stable_key": "python_basics", "title": "Python 基础", "nodes": [
            {"stable_key": "py_variable", "title": "变量与赋值", "description": "能说明变量赋值并运行示例", "is_core": True,
             "prerequisites": [], "required_capabilities": ["python"]}]},
        {"stable_key": "sql_basics", "title": "SQLite SQL 基础", "nodes": [
            {"stable_key": "sql_select", "title": "SELECT 查询", "description": "能编写简单 SELECT 查询", "is_core": True,
             "prerequisites": [], "required_capabilities": ["sql"]}]},
    ],
}, ensure_ascii=False)
original = LearningPlanDraftToolInput.model_validate_json(draft_json)
feedback = {"purpose": "main_teaching", "node": "py_variable",
            "covered": "变量与赋值可据公开摘录修订描述", "gap": "SQL 目标未由本摘录覆盖；必须保留"}
messages = [
    {"role": "system", "content": "只返回 JSON 对象，包含 schema_version 和 modules，遵守原有学习目标、节点和前置关系；仅依据公开摘录修订节点 description；不得伪造来源授权、评分或覆盖。"},
    {"role": "user", "content": "修订草案 JSON；只能调整 description。保留所有字段、模块/节点和两个核心目标。SQL 缺口必须如实保留。\n草案:" + draft_json + "\n材料反馈:" + json.dumps(feedback, ensure_ascii=False) + "\n公开摘录:" + excerpt},
]
if len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) > 6000:
    raise SystemExit("prompt byte cap exceeded")
llm_client.LLM_PROVIDER_RETRY_ATTEMPTS = 1  # 临时独立进程，最多一笔 HTTP 尝试
try:
    response = llm_client.OpenAICompatibleClient(settings).complete_json(
        messages, temperature=None, max_tokens=800, timeout_seconds=30,
        capture_provider_body=False,
    )
except (llm_client.LLMCallError, llm_client.LLMInvalidResponseError) as exc:
    # 不输出异常字符串、body 或堆栈；无 usage 时保持 None/unknown
    print(json.dumps({"status": "provider_error", "kind": type(exc).__name__,
                      "usage": asdict(exc.usage) if getattr(exc, "usage", None) else None}, ensure_ascii=False))
    raise SystemExit(1)
revision = LearningPlanDraftToolInput.model_validate_json(json.dumps(response.content, ensure_ascii=False))
a = original.model_dump(mode="json")
b = revision.model_dump(mode="json")
for old_mod, new_mod in zip(a["modules"], b["modules"], strict=True):
    for field in ("stable_key", "title", "is_core", "is_skippable"):
        if old_mod[field] != new_mod[field]: raise SystemExit("module identity changed")
    for old_node, new_node in zip(old_mod["nodes"], new_mod["nodes"], strict=True):
        for field in ("stable_key", "title", "is_core", "prerequisites", "required_capabilities", "catalog_knowledge_key"):
            if old_node[field] != new_node[field]: raise SystemExit("learning goal/graph changed")
if len(a["modules"]) != len(b["modules"]) or any(len(x["nodes"]) != len(y["nodes"]) for x,y in zip(a["modules"],b["modules"])):
    raise SystemExit("module/node dropped")
print(json.dumps({
    "status": "schema_and_goals_preserved", "model": response.model,
    "descriptions": [{"node": n["stable_key"], "description": n["description"][:300]}
                     for m in b["modules"] for n in m["nodes"]],
    "usage": asdict(response.usage) if response.usage else None,
    "diagnostics": asdict(response.response_diagnostics) if response.response_diagnostics else None,
}, ensure_ascii=False))
```

### What this proves

若成功，只证明**当次配置的真实既有 provider transport** 能以受限公开摘录和合成反馈返回一个符合既有计划 DTO、且身份/核心目标未删改的修订建议，并给出可得 usage/diagnostics；公开摘录的来源真实与可用性仍由 MAIN 独立检查。不是 D-AC2 的真实 Tutor dispatcher→context→provider→capability→新草案选择/持久 binding；不是 C 的当下准入、receipt/授权代次或 PG 同事务 fence；不证明公开消费者/评分发布或总费用余额。

## Related specs

- `.trellis/spec/backend/grounding-plan-material-consumption.md:3-15,39-54`：D default-off、真实运行和隔离测试分层、原稿目标保护、模型反馈不能替代受控绑定。
- `.trellis/spec/backend/index.md:21-26,43-49`：相关后端规格入口、当前代码和文档核验要求。

## Caveats / Not Found

- 没找到现成的“仅规划反馈修订”的独立客户端 DTO/方法；现有普通路径是完整 Tutor Gateway；草图直接调用同一个既有 LLM client 和计划工具 DTO，不冒充生产流水线。
- 本侧车未读取 `.env`、未查账单、未调用外部服务、未触碰真实 DB；当前 provider/model/host/secret-present 仍待 MAIN 在本地脱敏读取。没有查询外部文档；代码及项目政策为本报告唯一参考。
- 脚本为**草图，未经运行验证**。`model_validate_json` 或保留字段校验可能因 provider 输出无效而退出，此时仍可能有一次计费 HTTP 请求；必须保留该失败证据，不把缺失 usage 当零。

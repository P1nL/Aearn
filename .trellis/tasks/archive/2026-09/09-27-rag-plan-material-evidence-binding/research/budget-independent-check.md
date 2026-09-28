# 上下文预算修复独立复核（2026-09-27）

## 范围与结论

只复核 `tests/learning/test_catalog_artifact_scope.py`、`tests/tutor/test_tutor_context_budget.py` 与 `research/budget-repair.md`，对照现行 `context_budget.py`、`provider_request.py` 及实际 provider gateway 发送路径；没有真实 API、生产预算改动或提交。

1. **4096 旧断言确实过时，不是通过跳过拒绝分支“刷绿”。** 预算器先以 optional=0 构造 required selection，再经 `_estimate_complete_request` 用与首轮 provider 相同的 serializer、UTF-8 estimator、protocol reserve、safety margin 估算完整 messages；两处 required estimate 超硬上限直接 `TUTOR_CONTEXT_REQUIRED_OVERFLOW`。fixture 内存探针此前测得 required floor 3705、首轮完整估算 4049/3916，皆不超过 4096。改为仅 synthetic provider 的 input cap=3500，则 3500 < 3705；负例仍要求拒绝、provider.calls=0、artifact count=0。4096 正例要求 handle 和 artifact，且每轮 exact serialization estimate <= metadata <= cap。本复核重新在指定隔离 PG 库运行，两组测试共 17 passed。
2. **exact-fit 离线边界性质有效。** 测试不是将某个 token 数值硬编码成通过点：二分找最小可容纳的硬上限，按序列化完整 messages + 两种 reserve 复算，断言等于该上限，并核验少 1 token 拒绝。新增对 required fact 的 source ID、实际 JSON 内容和 missing_count=0 的断言，避免单靠计数误将替换/截断视作“完整”。
3. **但预算验收不能延伸为真实第二次 provider 请求也受界。** `app/services/tutor/provider_gateway.py:237-247` 在 retry 时重建已估算的首轮 messages，再附加 `build_tutor_replacement_message`，没有重估/限额；该补充指令在当前代码、空 issue/现有 teaching policy 下单独约 1971 UTF-8 估算 token / 6492 chars。对本 fixture 已测 4049/4096 首轮，附加后显然可超过输入硬上限。新增 3500/4096 双向测试使用 `_ArtifactTeachingProvider.decide` 而非真实 gateway client，故不覆盖 retry；更不能表述为所有 provider calls 的物理限额已证明。**这是预算链上独立的生产路径缺口，不宜靠进一步缩测试上限或改 metadata 掩盖。** 本次受限于用户只授权预算测试/研究切片，未编辑 gateway；建议主会话协调其并行 owner 后，按每次实际发送 messages（含 repair）重新预算或安全拒绝/缩减可选上下文，并加 retry 边界测试。

## 验证与边界

- 显式 `DATABASE_URL=postgresql://aearn_d@127.0.0.1:55438/aearn_repair_d_budget_20260927` 与同名 `AEARN_TEST_DATABASE_NAME`，`select current_database()` 确认该隔离库后运行目标测试：**17 passed**。未新建/清理库。
- `ruff check` 两目标测试文件：**pass**。
- `mypy --follow-imports=skip app/agents/harness/context_budget.py`：**pass（仅当前模块隔离）**。正常 mypy 追踪依赖则在并行更改的 `app/services/tutor/provider_gateway.py:526-542` 报 4 个类型错误；含测试文件的广泛 mypy 扫描还报告既有/并行依赖错误，不把受限 skip-import 结果冒称全库通过，也不在本切片抢改 gateway。
- 未运行全库或真实 provider；未认为 17 个测试等价于 D/E 发布验收。

## 补充：独立的 per-attempt retry-budget sidecar（2026-09-27）

按主会话后续授权新增 `app/services/tutor/provider_request_budget.py`（纯函数、没有 provider/DB/网络调用）和 `tests/tutor/test_tutor_provider_request_budget.py`；未编辑并行 owner 持有的 `provider_gateway.py`。公开函数签名：

```python
def assert_tutor_provider_request_budget(
    messages: Sequence[Mapping[str, str]],
    *,
    capability: TutorProviderContextCapability,
    estimator: TokenEstimator | None = None,
) -> int: ...
```

传入**本次即将发送的完整消息列表**，用 planner 相同 `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` 和 `Utf8ByteTokenEstimator`，加 `capability.protocol_reserve_tokens`、`capability.safety_margin_tokens`；不得超过 `capability.input_hard_limit`，它已从 context window 减去 output reserve，不能重复减。恰好相等允许；超限抛 `TutorContextError("TUTOR_CONTEXT_REQUEST_OVERFLOW")`，不得发请求或进入又一次 repair。无额外比例、双倍估算或任意魔法保留。若第一轮已经由 planner 估算，本守卫仍可在每次真实 client call 前统一执行。

**供 gateway owner 对接的插入位置与精确代码**：在 `PrimaryTutorProviderGateway.decide` 的 `for attempt_index ...` 内，`if attempt_index > 1` 重建并 `messages.append(replacement)` 结束后、现有 `try:`/`client.complete_json(...)` 之前。新增所需 import：

```python
from app.agents.harness.context_budget import resolve_tutor_provider_context_capability
from app.agents.harness.contracts import TutorContextError, TutorTerminalOutcome
from app.services.tutor.provider_request_budget import assert_tutor_provider_request_budget
```

插入（`attempts`、`projector`、`thinking_sink`、`run`、`self._settings` 均是现有局部对象）：

```python
            policy = run.policy.context_budget_policy
            capability = (
                policy.capability
                if policy is not None
                else resolve_tutor_provider_context_capability(self._settings)
            )
            try:
                assert_tutor_provider_request_budget(messages, capability=capability)
            except TutorContextError as exc:
                if projector is not None and thinking_sink is not None:
                    thinking_sink.discard_attempt(attempt_index)
                return TutorProviderResult(
                    decision=None,
                    terminal_outcome=TutorTerminalOutcome.FAILED,
                    safe_code=exc.safe_code,
                    attempts=tuple(attempts),
                )
```

现有 `begin_attempt` 在 guard 前；因此保留 `discard_attempt` 清掉未完成的 public-thinking attempt。更优结构可由 owner 将 guard 移到 begin 之前以不产生任何 provisional attempt side effect，但**必须保证 repair 已 append 且 guard 在 client call 前**。建议保持 `TUTOR_CONTEXT_REQUEST_OVERFLOW` 这一现有 safe code，明确是完整请求预算而非模型不可用；终态 FAILED、不重试、不捏造新 provider attempt/usage，保留上一次真实 rejected attempt receipt。待 owner 接入后加 gateway-level fake-client 回归：首轮 repairable invalid，附加消息超限，断言仅一笔 client call、第二次无 attempt receipt、终态与 safe code 正确。当前纯测试只能证明 helper+guard 调用顺序；不能宣称 gateway 已接线。

纯测试使用真实 `build_tutor_replacement_message`，证明 exact fit、少一 token 拒绝、首轮可容纳而修复请求超限以及阻止新的 fake-client call。命令 `uv run pytest -q tests/tutor/test_tutor_provider_request_budget.py tests/tutor/test_tutor_context_budget.py`：17 passed；`ruff check` 新 helper/test：pass；`mypy --follow-imports=skip` helper：pass。未调用真实 API。原并行 gateway mypy 错误状态仍需主会话完成并行合并后复验。

## Gateway 最终发送路径独立回归（2026-09-27，接线之后）

本轮仅修改 `tests/tutor/test_tutor_provider_request_budget.py` 并追加本记录，没有编辑 semantic owner 的 gateway。当前 `provider_gateway.py:252-263` 已在 repair append 后、两种 client.complete_json 分支前调用 helper，并在溢出时终态 FAILED。

新增真实 `PrimaryTutorProviderGateway.decide` 路径测试（不是手写 send wrapper）：
- fake client 首轮返回有 learner-visible thinking 的非法 action，触发真正的 parser repairable rejection；不 mock parser/repair builder。
- 依据真实首轮 serializer 的消息内容精确设置 input limit；测试 spy 只观察 helper 入参，仍调用原 helper。验证首轮 exact fit，第二次检查收到首轮消息加真正 repair 消息并超上限。
- assert client/transport 恰好调用一次；终态 FAILED，safe_code=`TUTOR_CONTEXT_REQUEST_OVERFLOW`，decision=None；仅保留真实首轮的 REPAIRABLE_REJECTED receipt、attempt_index=1，没有虚构的第二次 attempt。
- 同时覆盖 snapshot policy capability 和无 policy 时 Settings fallback 两分支。
- streaming 分支用真实 `OpenAICompatibleClient` + 纯 fake transport（没有 HTTP），验证首轮 provisional thinking 实际 append 后被 discard；第二轮 begin 后在发送前 discard，第二轮零 append，两轮均零 complete。

验证：
- 新文件：**7 passed**（3 pure + 4 gateway 参数组合）。
- 完整 `test_tutor_provider_gateway.py` + 新文件：**85 passed / 13 failed**。失败表现为旧 repair 测试期望第二次调用/旧 provider 错误码，但新的守卫返回 `TUTOR_CONTEXT_REQUEST_OVERFLOW`。这些默认 4K conservative-capacity fixtures 不能继续假定额外 repair 消息必定放得下；不据此删除守卫、缩减 reserves 或扩大生产默认上限。
- 失败涉及：current-input retry preservation（1）；deepseek invalid-response shapes content missing/not-json（2）；unsafe public thinking（1）；same-model invalid-envelope retry（1）；unknown/guardrail envelope（1）；nested protected-field 参数（4）；safe failure category content missing/not-json（2）；per-repair usage accounting（1）。建议测试 owner 给测试 retry/diagnostic 行为的 synthetic fixture 显式声明足够的有限容量，另保留本文件对真实小容量终态拒绝的验收。本轮不改该文件。
- Ruff 新测试：pass；Mypy `--follow-imports=skip` 新测试+helper：pass；正常依赖检查仍在并行 gateway 的 `issue` 变量类型复用（当前543/544/559行）报4个错误，未越界修改。
- 没有真实 API、DB、提交，也未将广泛 suite 的13个失败报告成绿色。

## 获准的旧 retry fixture 兼容修复（2026-09-27）

本轮仅修改 **1 个测试文件**：`tests/tutor/test_tutor_provider_gateway.py`（另追加本研究记录）。新增 `_retry_run()`：为专门验证 retry/diagnostic 的 synthetic provider 显式提供 **8192 input + 4096 output reserve** 的有限 snapshot capability，仍由既有 Settings→budget policy 解析，protocol/safety reserve 不削减。8 个测试函数、9 处 gateway dispatch 显式改用该 helper，覆盖此前13个参数化失败；普通 `_run()`、低预算/默认预算发送路径测试、生产 Settings 和最终 guard 全部保持不变。没有删除或放松原调用次数、终态、诊断码、usage、隐私/消息完整性断言。

修复后全量两文件 `uv run pytest -q tests/tutor/test_tutor_provider_gateway.py tests/tutor/test_tutor_provider_request_budget.py --tb=short`：**98 passed**（原85 passed / 13 failed 全部转为通过，其中新预算文件7个测试仍通过）。

`ruff check` 两测试文件：pass。`mypy app/services/tutor/provider_request_budget.py app/services/tutor/provider_gateway.py` 正常依赖检查：**pass**；semantic owner 的 gateway 类型冲突已在当前快照消失，本代理没有写生产 gateway。`git diff --check`：pass（仅LF/CRLF提示）。未调用真实 API、未操作DB、未提交。此前13失败及类型错误记录保留为修复前事实，不覆盖历史记录。

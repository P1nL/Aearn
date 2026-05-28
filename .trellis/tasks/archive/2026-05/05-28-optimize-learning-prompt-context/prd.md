# Optimize learning page prompt and context

## Goal

提升 Aearn 学习页日常对话的“聪明感”和教学有效性，让最新模型不再被过短、过保守、上下文过薄的 prompt 合同压成流程化回复，同时保留 concept-first 产品边界和安全 guardrails。

用户反馈的核心问题是：实际使用中模型显得“有点傻”，但配置模型已经是最新的。初步代码检查显示，主要风险来自学习页 prompt 与输入上下文合同，而不是模型能力本身。

主要入口：

- `aearn/services/api/app/services/learning_conversation.py` 的 `_build_messages`
- `aearn/services/api/app/agents/learning_conversation_agent.py` 的 `AgentsSDKLearningConversationClient`
- `aearn/services/api/app/agents/guardrails.py` 的 teaching input/output guardrails

外部参考：

- `earendil-works/pi` 的 compaction 设计：用结构化 summary 保留旧上下文，同时保留最近消息进入模型上下文；Aearn 可借鉴这个“summary + recent context”的混合模型，但需要替换为学习场景的 safe learning summary。

## Requirements

- P0 体验目标是“更像真人导师的连续对话”，而不是单纯更快把用户推到练习。
- 优化学习页 agent prompt，使其从“短、保守、流程化”转向类似 skill 的可执行导师手册，包含身份、工作循环、诊断树、阶段策略、上下文使用、答案请求处理、输出形状和安全反例。
- 模型回复应体现对用户当前表达的理解：先判断用户是在困惑、误解、验证理解、请求捷径，还是需要练习支持，再选择教学动作。
- 真人导师感优先体现在“诊断与追问”：先识别用户卡点或潜在误解，再选择是否追问、解释、给例子或推进练习。
- 诊断顺序采用“先判断再追问”：先用低置信措辞说明当前判断，再问一个能缩小卡点的问题。
- 保留 concept-first 学习路径：概念阶段仍不能直接展开完整题面、starter code、标准答案或 hidden test 细节。
- 当用户直接索要答案、完整代码或标准解法时，Agent 不应只做生硬拒绝；应承认诉求、说明不能代写完整答案，然后给具体局部提示、最小检查方向或下一步练习动作。
- 改善模型输入上下文，不只给当前 `learner_message`；允许纳入近期对话上下文，但必须是安全摘要和少量安全消息，不直接把所有历史原文塞进模型。
- 上下文策略参考 `earendil-works/pi`：旧对话压缩为结构化 safe summary，最近对话保留为少量安全消息；不要采用“全历史原文”或“只有摘要无最近语气”的极端方案。
- 第一版 `recent_safe_messages` 默认保留最近 4 条安全消息，通常覆盖 2 轮 user/agent；旧内容交给 LLM summary。
- 近期上下文应帮助模型识别用户连续困惑、反复误解、刚刚做过的解释、以及当前应该追问还是推进。
- `safe_summary` 由 LLM 生成，而不是第一版只用确定性模板；但摘要生成必须在安全过滤后的输入上执行，并对摘要输出再次执行 teaching guardrail。
- LLM summary 不每轮刷新；采用阈值/过期刷新策略，例如 summary 缺失、最近安全消息超过阈值、或出现新的诊断/误解时刷新。
- `safe_summary` 必须持久化到数据库，确保刷新、重启或跨请求后仍能恢复真人导师式连续上下文。
- 第一版默认复用现有 `learning_sessions.learning_stage_state_json` 存储摘要状态和刷新元数据，不新增专用 summary 表；`learning_messages` 继续作为近期消息来源。
- 如果 LLM 摘要失败、超时、输出踩线或配置不可用，系统必须降级到确定性 safe summary 或空摘要，不应阻断学习对话主流程。
- Guardrail 不删除；如用户请求完整答案或模型输出踩线，应优先转成教学式引导或安全 fallback，而不是直接泄露。
- 设计应覆盖 `concept_intro`、`concept_qna`、`readiness_check`、`practice_support` 四个阶段，避免所有阶段共用同一套短回复逻辑。
- 验证必须证明不会泄露 hidden tests、`solution_reference`、provider raw errors、API key 或 raw prompt。
- 不处理 `.claude/settings.local.json`、`docs/.obsidian/` 这两个当前未跟踪本地项。

## Acceptance Criteria

- [ ] PRD 明确“真人导师式连续对话”是首要目标，并说明它优先于快速推进练习。
- [ ] Runtime prompt 不是短规则摘要，而是足够详细的执行手册，能稳定约束模型如何诊断、追问、承接上下文和处理答案请求。
- [ ] Prompt/input 合同让模型能根据学习阶段给出更自然、有上下文感的回复。
- [ ] 回复能根据用户意图选择不同教学动作，例如澄清误解、给类比、给最小例子、追问、建议练习或复盘错误。
- [ ] 回复优先体现诊断能力：明确“我判断你可能卡在 X”，并在需要时只提出一个高价值追问。
- [ ] 诊断回复遵循“判断 -> 单个追问 -> 下一步”的形状，避免连续盘问或一次抛出多个问题。
- [ ] 近期对话上下文必须只传 safe summary 和少量安全消息，不传 hidden case id、reference answer、provider errors、API key、raw prompt 或其他原始敏感字段。
- [ ] Safe summary 至少覆盖学习目标、用户当前卡点、已解释过的关键概念、已确认误解、最近一次诊断、建议下一步。
- [ ] LLM summary 的输入和输出都被安全过滤；测试覆盖摘要生成不能泄露 hidden/reference/provider/API-key/direct-answer 内容。
- [ ] Summary refresh 不应每轮无条件调用 LLM；测试或代码结构能体现阈值/过期刷新规则。
- [ ] Summary 状态持久化到数据库，跨请求/刷新后仍能进入 `_build_messages`。
- [ ] LLM summary 失败时有确定性 fallback，不影响主对话生成。
- [ ] 加入近期上下文后，模型回复能体现连续性，例如避免重复上一轮解释、能承接用户刚刚的困惑、能修正自己的诊断。
- [ ] 用户直接索要答案时，系统能转向具体局部提示、检查方向或最小示例，而不是只显得拒绝或机械；但仍不输出完整答案或完整代码。
- [ ] 相关回归测试覆盖 guardrail、安全摘要、模型输出被拦截后的 fallback。
- [ ] 运行可发现的最小验证命令，例如 `tests/test_llm_integration.py` 和 `tests/test_learning_sessions_m3.py` 中相关用例。

## Confirmed Facts

- 当前学习页 LLM 调用会把 `_build_messages` 生成的 `system` 作为 instructions，把 `user` JSON 作为 input，并接入 teaching guardrails。
- 当前 prompt 明确要求“只基于输入 JSON 回答”“回复短、具体、可执行”“概念阶段不得展开完整题面、starter code 或答案”。
- 当前 `_build_messages` 主要传 stage、knowledge point、lesson outline、concept progress、practice 阶段 exercise、latest attempt 和当前 learner message；没有直接把近期对话历史作为普通 messages 注入模型。
- 当前 schema 已有 `learning_sessions.learning_stage_state_json`，适合存会话级学习阶段状态；`learning_messages.metadata` 已用于 agent message metadata。
- 当前 guardrails 是硬安全边界，不应作为首要删除对象。
- 当前任务还处于 planning；创建任务不代表已经批准 implementation。

## Decisions

- 首要优化目标：更像真人导师的连续对话。
- 快速推进练习是次级目标；只有在用户已经表达准备好、请求练习、或 readiness 判断通过时才应主动进入练习。
- 真人导师感的第一优先级：诊断与追问，而不是单纯让讲解更长或例子更多。
- 诊断顺序：先判断再问。推荐措辞应使用“我判断/看起来像/可能卡在”，避免把不确定诊断说死。
- 直接索要答案时：不给完整答案，但给足够具体的局部提示和下一步，避免生硬拒绝。
- 允许近期对话上下文进入模型输入，但只能通过安全摘要和少量安全消息进入，不直接传完整历史原文。
- 上下文形态：参考 `earendil-works/pi` 的混合压缩思路，采用“结构化 safe summary + 最近少量安全消息”，而不是只传摘要或只传最近原话。
- `safe_summary` 生成方式：调用 LLM 生成；需要输入过滤、输出 guardrail 和 deterministic fallback。
- Summary refresh 策略：阈值/过期刷新，而不是每轮刷新。
- Summary 持久化：写入数据库。第一版使用 `learning_sessions.learning_stage_state_json` 中的专用 `conversation_summary`/refresh metadata 结构，不新增表。
- 最近安全消息：默认 4 条；如果用户连续发多条极短消息，允许实现层合并为一个近期 user context。

## Open Questions

- No product-blocking open questions remain. Exact implementation constants can be adjusted during Phase 2 if tests show better thresholds.

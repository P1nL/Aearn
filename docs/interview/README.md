# Aearn Agent 面试手册

这是一份基于真实项目代码的中文面试材料：**15 个专题、55 道核心题、165 组带答案的追问**，另含三种时长讲述稿和三类架构图。不是通用题库，也不承诺穷尽所有面试问题。

- [完整手册：项目讲述、专题答案和连续追问](aearn-agent-design-handbook.md)
- [证据索引：代码定位、验证范围和不能夸大的事项](aearn-agent-interview-evidence.md)
- [返回项目文档索引](../README.md)

**源码基线：** `4b595e0507282c01d8f36840990671cfcf3420a3`。**核对日期：** 2026-09-16。文档是现有运行时规格的派生学习材料，发生冲突时回到当前代码、测试与配置核对；这不是发布批准。

## 建议阅读顺序

1. 先看 [项目讲述稿](aearn-agent-design-handbook.md#项目讲述稿)，确认自己实际负责的范围，不机械套用第一人称。
2. 读 01、02 建立业务与调用链认识，再重点读 03 框架选型和 05 上下文工程。
3. 结合 09、10、11 理解工具权限、恢复与教学闭环，再读 12～15 的安全、交互、评估和演进。
4. 每题先练短答，再讲完整机制；用连续追问检查是否能解释边界，最后打开证据定位。

## 专题导航

| 专题 | 主题 | 核心题 | 主要关注点 |
| --- | --- | ---: | --- |
| 01 | [项目定位与 Agent 必要性](aearn-agent-design-handbook.md#topic-01) | 3 | 为什么需要 Agent，如何定义成功 |
| 02 | [总体架构与完整调用链](aearn-agent-design-handbook.md#topic-02) | 3 | 输入、调度、运行、提交和展示 |
| 03 | [框架选型](aearn-agent-design-handbook.md#topic-03) | 8 | 现役框架、替代方案及历史边界 |
| 04 | [决策与规划](aearn-agent-design-handbook.md#topic-04) | 3 | 结构化决策、语言确认与计划确认 |
| 05 | [上下文工程](aearn-agent-design-handbook.md#topic-05) | 8 | 来源、优先级、预算、压缩与隔离 |
| 06 | [记忆与学习者状态](aearn-agent-design-handbook.md#topic-06) | 3 | 摘要、推断记忆、课程事实与作用域 |
| 07 | [RAG 与知识来源](aearn-agent-design-handbook.md#topic-07) | 3 | 已有 grounding、运行时接线和 RAG 规划 |
| 08 | [Prompt/Skill/协议](aearn-agent-design-handbook.md#topic-08) | 3 | 提示词、Skill、版本与协议 |
| 09 | [工具调用与执行权限](aearn-agent-design-handbook.md#topic-09) | 3 | 能力调用、副作用与服务端权限 |
| 10 | [状态机、持久化与恢复](aearn-agent-design-handbook.md#topic-10) | 3 | checkpoint、修订、幂等与恢复 |
| 11 | [教学业务闭环](aearn-agent-design-handbook.md#topic-11) | 3 | Artifact、评分、Gate、补救与复习 |
| 12 | [安全与代码执行隔离](aearn-agent-design-handbook.md#topic-12) | 3 | 注入、受控执行器与隐私 |
| 13 | [流式交互与前后端一致性](aearn-agent-design-handbook.md#topic-13) | 3 | SSE、重连、取消与权威刷新 |
| 14 | [评估、测试与可观测性](aearn-agent-design-handbook.md#topic-14) | 3 | 评估分层、事实保真与故障定位 |
| 15 | [性能成本与演进](aearn-agent-design-handbook.md#topic-15) | 3 | 调用预算、流量控制与优化方法 |

## 全部核心问题

| 题号 | 问题 |
| --- | --- |
| [AG-01-001](aearn-agent-design-handbook.md#ag-01-001) | 为什么 Aearn 需要 Agent，而不是在聊天框后面接一个大模型？ |
| [AG-01-002](aearn-agent-design-handbook.md#ag-01-002) | 你怎样定义这个学习 Agent 的成功，而不只看回答是否流畅？ |
| [AG-01-003](aearn-agent-design-handbook.md#ag-01-003) | 面试时怎样介绍个人工作与项目难点，才能经得起追问？ |
| [AG-02-001](aearn-agent-design-handbook.md#ag-02-001) | 从用户发出一条消息，到页面出现教学结果，完整链路是什么？ |
| [AG-02-002](aearn-agent-design-handbook.md#ag-02-002) | 为什么已经用了 Celery，还要在 PostgreSQL 里保留任务和状态？ |
| [AG-02-003](aearn-agent-design-handbook.md#ag-02-003) | 用户、会话和课程的隔离在哪里做？能直接称为生产级多租户系统吗？ |
| [AG-03-001](aearn-agent-design-handbook.md#ag-03-001) | Aearn 当前到底用了什么 Agent 框架，是否还是 LangGraph 或 Agents SDK？ |
| [AG-03-002](aearn-agent-design-handbook.md#ag-03-002) | 为什么有了 Agent 框架，业务状态仍必须由服务端掌握？ |
| [AG-03-003](aearn-agent-design-handbook.md#ag-03-003) | 为什么不直接用 LangGraph？它能解决什么，又不能替项目决定什么？ |
| [AG-03-004](aearn-agent-design-handbook.md#ag-03-004) | OpenAI Agents SDK 与自建 Harness 有什么区别，为什么不能把 SDK guardrail 当业务保证？ |
| [AG-03-005](aearn-agent-design-handbook.md#ag-03-005) | 直接调用模型 API、自建 Harness 和使用 Agent 框架，是互斥选择吗？ |
| [AG-03-006](aearn-agent-design-handbook.md#ag-03-006) | Codex Sidecar 在项目中做什么，为什么不是把完整编码代理直接交给学习者？ |
| [AG-03-007](aearn-agent-design-handbook.md#ag-03-007) | Harness 与 Codex 如何选路，故障时为什么不直接互相兜底？ |
| [AG-03-008](aearn-agent-design-handbook.md#ag-03-008) | 怎样诚实回答“为什么从 Graph/SDK 迁移到自建”，并评估未来是否换回框架？ |
| [AG-04-001](aearn-agent-design-handbook.md#ag-04-001) | 模型如何决定下一步，怎样防止自由文本直接变成业务操作？ |
| [AG-04-002](aearn-agent-design-handbook.md#ag-04-002) | 学习者只说“想做后端”时，如何确定语言，又为什么不能让模型直接确认 Python？ |
| [AG-04-003](aearn-agent-design-handbook.md#ag-04-003) | 学习计划是模型直接保存的吗？草稿、确认和能力校验如何衔接？ |
| [AG-05-001](aearn-agent-design-handbook.md#ag-05-001) | 一次Tutor决策的上下文究竟来自哪里，为什么不能直接取聊天记录最后一条？ |
| [AG-05-002](aearn-agent-design-handbook.md#ag-05-002) | 预算不够时先保留什么、删掉什么？“必需上下文”是否绝不会被截断？ |
| [AG-05-003](aearn-agent-design-handbook.md#ag-05-003) | 如何估算一次请求的token？只统计用户输入为什么不够？ |
| [AG-05-004](aearn-agent-design-handbook.md#ag-05-004) | 百万上下文、128K输入和16K输出在项目中分别代表什么？ |
| [AG-05-005](aearn-agent-design-handbook.md#ag-05-005) | Aearn如何按任务复杂度分配上下文，而不是一直使用同一预算？ |
| [AG-05-006](aearn-agent-design-handbook.md#ag-05-006) | 聊天很长时如何压缩，怎样避免把尚未确认的事实压没？ |
| [AG-05-007](aearn-agent-design-handbook.md#ag-05-007) | 把Lesson选区、执行结果或知识检查放进Prompt，如何避免越权和泄露？ |
| [AG-05-008](aearn-agent-design-handbook.md#ag-05-008) | Codex线程压缩、Harness压缩envelope和Teaching checkpoint是不是一回事？ |
| [AG-06-001](aearn-agent-design-handbook.md#ag-06-001) | 长期记忆是什么，模型能不能自行给学习者写一个永久标签？ |
| [AG-06-002](aearn-agent-design-handbook.md#ag-06-002) | 工作摘要、学习者记忆和课程状态冲突时，谁说了算？ |
| [AG-06-003](aearn-agent-design-handbook.md#ag-06-003) | 同一条长期对话中，知识点切换和Artifact澄清分支怎样避免串状态？ |
| [AG-07-001](aearn-agent-design-handbook.md#ag-07-001) | Aearn 当前实际怎样检索知识，能称为混合检索吗？ |
| [AG-07-002](aearn-agent-design-handbook.md#ag-07-002) | 如何证明课程引用来自可信资料，而不是模型生成了一个看似官方的链接？ |
| [AG-07-003](aearn-agent-design-handbook.md#ag-07-003) | 既有 grounding 能力、Tutor 实际入口与 RAG 2.0 规划应该怎样分开讲？ |
| [AG-08-001](aearn-agent-design-handbook.md#ag-08-001) | 为什么同时有Prompt、Skill和Capability，不直接写一个大system prompt？ |
| [AG-08-002](aearn-agent-design-handbook.md#ag-08-002) | Skill版本如何保证可复现？为什么不能直接修改旧instructions再重算hash？ |
| [AG-08-003](aearn-agent-design-handbook.md#ag-08-003) | 模型输出合法JSON就能执行业务动作吗？决策协议怎样分层验证？ |
| [AG-09-001](aearn-agent-design-handbook.md#ag-09-001) | Skill、capability、effect 与服务端权限是什么关系？ |
| [AG-09-002](aearn-agent-design-handbook.md#ag-09-002) | 模型提出写操作后，如何防止过期结果和重试产生重复副作用？ |
| [AG-09-003](aearn-agent-design-handbook.md#ag-09-003) | 学习者点击 Run 时，执行授权为什么不能只靠前端按钮？ |
| [AG-10-001](aearn-agent-design-handbook.md#ag-10-001) | 为什么教学 checkpoint 不能只放在模型历史或进程内存里？ |
| [AG-10-002](aearn-agent-design-handbook.md#ag-10-002) | 同一 Conversation 收到新输入后，Turn 与 input_revision 怎样阻止旧结果提交？ |
| [AG-10-003](aearn-agent-design-handbook.md#ag-10-003) | 自动续教如何恢复而不重复开回合，也不抢走学习者正在进行的交互？ |
| [AG-11-001](aearn-agent-design-handbook.md#ag-11-001) | 一次正式 Gate 提交怎样更新 Attempt、掌握度与课程进度？ |
| [AG-11-002](aearn-agent-design-handbook.md#ag-11-002) | 用 Hint、看答案、做补救题之后，如何避免把“被帮助的正确”算成独立掌握？ |
| [AG-11-003](aearn-agent-design-handbook.md#ag-11-003) | Review 为什么按有限会话统一结算，而不是每做一道题就更新复习计划？ |
| [AG-12-001](aearn-agent-design-handbook.md#ag-12-001) | 如果学习材料或用户消息里出现 Prompt Injection，系统靠什么限制后果？ |
| [AG-12-002](aearn-agent-design-handbook.md#ag-12-002) | 让学习者运行代码如何隔离？为什么不能说“用了 Docker 就安全”？ |
| [AG-12-003](aearn-agent-design-handbook.md#ag-12-003) | 怎么在可观测性与隐私之间取舍？日志和流式输出是否一样处理？ |
| [AG-13-001](aearn-agent-design-handbook.md#ag-13-001) | 为什么使用 SSE？传输的只是模型 token 吗？ |
| [AG-13-002](aearn-agent-design-handbook.md#ag-13-002) | 网络断开、事件重复或中间丢失时，页面怎样恢复？ |
| [AG-13-003](aearn-agent-design-handbook.md#ag-13-003) | 怎样避免“前端看起来已停止或已通过，但后端其实不是”的假状态？ |
| [AG-14-001](aearn-agent-design-handbook.md#ag-14-001) | 如何测试 Agent？为什么“几个问题回答得不错”还不够？ |
| [AG-14-002](aearn-agent-design-handbook.md#ag-14-002) | 怎样证明上下文策略改善了效果，而不只是减少了 token？ |
| [AG-14-003](aearn-agent-design-handbook.md#ag-14-003) | 真实调用失败时，你怎么定位，而不是不停改 Prompt 或重试？ |
| [AG-15-001](aearn-agent-design-handbook.md#ag-15-001) | 怎样控制模型调用成本，为什么 max_model_calls 不是账单请求数？ |
| [AG-15-002](aearn-agent-design-handbook.md#ag-15-002) | 流式输出越快越好吗？怎样处理慢消费者、失控工具和取消后的残留执行？ |
| [AG-15-003](aearn-agent-design-handbook.md#ag-15-003) | 没有性能数据时，怎样提出可信的优化与框架演进计划？ |

## 先记住这些事实边界

- 当前主运行时是 Tutor Harness，Codex 是受控规划分支；旧 Graph/SDK 不能当作现役实现。
- 大模型窗口、应用输入 cap、普通决策输出、压缩 envelope 和线程压缩不是一个数。
- 当前教学 Skill 源码与部分旧说明存在版本差异，详见证据索引；没有为了写手册而修改业务配置或旧规格。
- 持久化 grounding 的存在，不代表每轮交互式 Tutor 都实际调用同一检索路径。
- 容器执行器有代码不等于已启用：当前审核 image-lock 清单为空，不能宣传为生产可用。
- 已实现、测试文件存在、测试实际通过、真实 provider/DB 验收和正式上线是不同结论。

本轮交付只改变文档。未新跑真实模型、数据库验收、压测或部署；没有自动提交或推送这些面试文档。

# 04 语言文档 Grounding 产品化审查稿

## 你需要审核的结论

这个子任务不是“接入实时网页搜索”，而是把已经存在的 `grounding_*` 服务层产品化：官方/可信文档先通过 allowlist 和 fixture/reindex 流程进入本地索引，学习对话运行时只查本地索引，并在使用时带 citation 元数据。

## 范围

- 新增本地持久化 docs grounding index。
- 支持无网络 fixture seed，方便本地测试和开发。
- 学习 agent 同时拿到两类上下文：课程内 `teaching_chunks` 和官方/可信文档 grounding。
- 如果用了官方/可信文档，响应和消息 metadata 带安全 citation 信息。
- grounding 缺失或失败时不崩溃，退回课程内上下文。

## 不做

- 不做任意 live web RAG。
- 不做 vector database 或 embedding 检索。
- 不做自动爬站或后台抓取。
- 不做环境安装指导；那是 `05`。
- 不做语言 runner 扩展；那是 `06`。

## 关键设计取舍

- 保留 `prd.md` / `design.md` / `implement.md` 为英文 canonical 文档，额外提供本中文审查稿。
- docs grounding 和课程内 RAG 分开，不混在同一张表或同一个 prompt 字段里。
- 运行时聊天不调用 fetcher，避免模型缺资料时临时联网抓取。
- Citation metadata 只包含 URL、source、trust tier、hash、时间和匹配原因，不带 prompt、隐藏测试、答案或原始 docs 大段内容。

## 验收重点

- fixture reindex 可以无网络生成并持久化 chunks。
- 同一来源重复 reindex 不产生重复脏数据。
- 学习对话可以读取 persisted docs grounding，并返回安全 citation metadata。
- 没有 grounding index 时学习对话仍然正常。
- 测试证明 chat runtime 不依赖 live fetch。

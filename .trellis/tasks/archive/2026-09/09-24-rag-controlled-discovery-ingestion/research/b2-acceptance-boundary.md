# Research: B2 验收边界独立核对

- Query: 核对本任务新写 `prd.md`/`design.md` 的 B2 缺口，尤其受限 fetch 与网络出口的分层证明、retention 和私有数据；校验 `transport-seams.md`。B1 预算/作业不重复。
- Scope: internal
- Date: 2026-09-24

## Findings

### 文件与证据位置

- `.trellis/tasks/09-24-rag-controlled-discovery-ingestion/prd.md:13-16,22-24,26-30`：现行 B2 需求、验收、非目标与开放问题；`design.md:7-13,17-20`：传输、暂存、数据分类、网络隔离和现场证明设计。
- `.trellis/tasks/09-03-rag-language-ecosystem-adaptive-retrieval/phase-ii-design.md:12-21,44-64,82-86`：父计划四层权限、B2、C 的分工；`phase-ii-implement.md:41-49`：B2 工作/验收，`:51-64` 将用途审核与正式入池留给 C。
- `.trellis/tasks/09-03-rag-language-ecosystem-adaptive-retrieval/source-selection-extension.md:23-27,38-42`：公开可读不自动准许保存全文，新站点在预授权探查范围内可自主发现，硬政策与软偏好分开。
- `.trellis/tasks/archive/2026-09/09-24-rag-material-source-contracts/prd.md:28-49`：A 只交严格合同/默认关闭，不交真实网络、存储、政策 resolver；`.trellis/spec/backend/grounding-material-contracts.md:11-27,37-41`：A 的捕获范围与离线证明边界。
- `.trellis/tasks/09-24-rag-controlled-discovery-ingestion/research/transport-seams.md:5-14`：已有传输/解析接缝判断；`research/persistence-seams.md:24-30,45-49`：暂存与共享/私有数据分类接缝。
- `docs/README.md:1-20`：现行文档索引；`.trellis/spec/backend/grounding-corpus-operations.md:19-30`：旧 CLI 的 fetch 未准备好，fixture 不是实抓材料。

### 精简结论：现有 PRD/design 已覆盖主边界，建议补强验收可判定性

1. **分开三个证据层，不互相替代。** `prd.md:22,24` 和 `design.md:7,12-13` 已明确 egress/未执行，但 AC 可再写成：离线受控 transport 测应用逐跳 URL→DNS→经核验公网 IP 的实际连接/peer、redirect、压缩前后上限、取消及 fail closed；独立的受限部署出口测试证明 worker 不能连 loopback、私网、link-local/metadata（含重定向与 IPv4/IPv6）；在取得部署网络/费用/来源许可后，代表性真实 HTTPS fetch 再证明请求链、最终 peer、TLS、内容哈希和持久化。前两层的 mock 各不能宣称第三层通过，应用 mock 不能证明出口；无出口证据时 live fetch `not_executed` 且运行时关闭。父据 `phase-ii-design.md:48-52,85-86`、`phase-ii-implement.md:43,49`；旧客户端仅 default `httpx.Client` 和整段 `response.text`：`aearn/services/api/app/services/grounding/grounding_fetcher.py:62-82`。
2. **许可应在探查、临时捕获和长期保存之间明确裁决。** `prd.md:13-14,22-23` 与 `design.md:7-8,13` 已说存储/保留分离，但 AC 尚未逐类断言：对未获原文保存许可、只允片段、只允 hash/locator、到期与撤权分别检查“可抓取最小探查内容”与“何种内容可落盘/保留多久”；解压临时文件、失败样本、队列负载、日志、解析缓存、审计 receipt 也不得成为全文绕道。清理应删内容并使指针不可读，但保留许可允许的最小非秘密审计元数据；政策未知默认拒绝保存，不由“公开可见”推导授权。父据 `phase-ii-design.md:12-21,50-52`、`source-selection-extension.md:23-25,40`；A `source_policy.py:44-78` 仅有 resolver 判定，非真实 retention 实现。
3. **私有数据分类可加一条隔离反例。** `prd.md:16,23`、`design.md:8,11` 已有共享/个人映射，但 AC 可显式用两名用户同一公开资料 demand 验证：共享候选/文档/审计收据不能反推出 learner 原始对话、用户标识、私有 URL/code/token；私有 demand→共享 job 的引用不进入公开查询或共享导出；用户导出只含获准个人关联，清理仅删除本人关联及私有文本、不删除共享来源事实，也不使其他用户引用悬空；私有仓库/登录/付费资料不进入共享 staging。父据 `phase-ii-design.md:21,28,42,50-52`、`autonomous-corpus-extension.md:21-28,123-125`；`persistence-seams.md:24-30`。
4. **来源凭据的捕获范围/隔离状态需要用例而非只列字段。** `prd.md:14-15,23`、`design.md:8,17` 已覆盖 provenance、hash、staging；AC 可断言真实请求链/最终 URL/时间、原文捕获 none/prefix/full 与各自 hash、不许把 prefix 当 full，不许以 search snippet、模型记忆、repo_page 或浮动分支冒充已抓取不可变 repo_file；同源镜像/翻译不伪增独立来源。staging 候选、解析片段、未核验 claim 经正式 retrieval/plan/题库/active pointer 路径均不可见，B2 不做 C 的教材用途/评分 claim 审核。A `contracts.py:119-154`、`.trellis/spec/backend/grounding-material-contracts.md:23-25`；父 `phase-ii-implement.md:47-49,51-59`。
5. **解析验收已有方向，需可复验 fixture。** `design.md:7` 要保留代码/列表/表格；旧 HTML parser 把 `pre/code` 与普通文字同样折叠空白，且未识别 table：`aearn/services/api/app/services/grounding/grounding_processing.py:52-55,82-125,267-268`。为 B2 独立解析用例增加代码缩进与换行、列表层级、表格单元、乱码/截断/错误 MIME、提示注入不执行/不授信；旧 fixture/hash/retrieval 单独回归，不能直接改旧 parser 后声称兼容。父 `phase-ii-implement.md:45-49`。

### 对 `transport-seams.md` 的准确性与遗漏

- `:5-10` 对旧 fetcher 非安全新候选抓取器、旧 parser 空白折叠、`httpx` 只在 dev 依赖（`aearn/services/api/pyproject.toml:6-27`）、应用级防护不代替 egress 的判断成立。旧 URL 检查还有允许 `http` 与 80/443 的遗留行为（`grounding_fetcher.py:215-227`），B2 的 HTTPS 约束不能靠原函数复用；旧错误消息截取异常文本（`:235-239`），新安全 receipt 不应泄漏 URL 中敏感部分或私有正文。
- 遗漏的主要是：探查许可≠原文保留许可、临时/失败/日志副本的 retention 覆盖、捕获范围 hash 语义、两个用户共享候选时的私有映射/导出/清理、mock/应用/egress/live 四种证据不得混同。上述补充与本任务 `prd.md:13-16,22-24`、`design.md:7-13` 一致，并非要求更改已写文件。
- `:11` 的首版 HTML/Markdown/plaintext 和排除 PDF/JS 是实施建议；本任务 `prd.md:26-27` 现已明确动态浏览器/PDF 等非目标，故 PDF/JS 排除有本任务依据，但 Markdown/plaintext 精确 MIME 清单仍非已冻结要求。`:12` 的 Tavily参数/receipt 归 B1，本研究不复核。

### 剩余用户决策

- `prd.md:29-30` 的“无阻断产品决策”与现有默认关闭方案可共存：不需临时逐页批准；但真实 fetch 前仍需部署责任人批准可探查域/path、出口隔离配置与实际验证环境、StorageRetentionPolicy 的全文/片段/hash 许可及期限、撤权后清理规则。没有这些时 B2 可以完成离线设计/测试，不能声称 live 验收或开启抓取（`phase-ii-implement.md:43,49`；`phase-ii-design.md:12-21,85-86`）。精确 MIME/大小/时间上限属于实施/部署参数，未授权时不得自造宽松默认值。

## Related Specs / External References

- `.trellis/spec/backend/index.md:17-24`、`grounding-material-contracts.md:9-41`、`grounding-corpus-operations.md:19-30`。外部参考：无；本轮无网络/provider/DB/密钥/测试调用。

## Caveats / Not Found

- 现行 `aearn/services/api/app/services/grounding/autonomous/` 仅 A 合同/策略，无可核验的 B2 fetch/staging/retention 或网络出口部署证明；`transport-seams.md` 是设计研究，不是 live 通过报告。此处只是 PRD 验收补充建议，未改 PRD/design、代码或现有政策。
- 工作树可能并行变化；以上路径/行号是本轮读取的 2026-09-24 快照，后续合并前应再核对。未执行 Git 操作、回退、抓取或测试。

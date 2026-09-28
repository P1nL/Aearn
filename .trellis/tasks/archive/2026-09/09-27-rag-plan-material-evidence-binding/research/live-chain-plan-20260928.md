# 真实全链路优先执行计划

用户明确要求先跑通真实全链路，结束语约束本轮不扩写。主机Get-Date实际记录2026-09-28T00:02+08:00；沿用本任务与项目开发期授权，不新建任务、不提交/推送/公开发布。

## 恢复原则
1. 使用同一真实隔离库aearn_rag260_c_d_live_repair_01a0e0c7，保留原unknown与错误但未消费的不可变补充授权。不能换库/删除记录来绕过派发边界。
2. 实施极窄的operator纠正接口：仅未消费补充授权可被追加式撤销；旧行不变；同一原始attempt最多一次纠正，且仅允许一个有效replacement。已派发/已消费不可撤销重发，仍禁止补充授权链式增加抓取预算。replacement使用现行成功合同要求的新policy/generation/root，精确绑定同一原始attempt/URL及新的dispatch/request。
3. 独立测试与复核锁顺序、双并发、旧授权拒绝、已消费拒绝、双bootstrap与审计不可变后，才应用到真实隔离库。
4. C完整GET可显式协商gzip；B默认不变，前缀仍identity，压缩/展开各8MiB、期限30秒、redirect0、安全pin/Unix/防火墙门禁不变。不得curl或partial冒充full。

## 实际验收
- 一次新的已纠正补充worker调用，之前重建并核对immutable image/code、B/C pins、namespace和11项DROP等门禁。
- 成功后同一库调用既有可信SQLite自动审核服务，确切WHERE/LIMIT片段、supplementary用途与schema/main/scoring缺口保留；不复制旧回执或手写质量通过。
- 通过真正的Primary gateway/API流程产生真实首稿，再由真实材料反馈驱动真实修订与语义review、重新selection和binding入库。fixture首稿不改标real。
- 每阶段最多8个实际model POST（初稿+修订合计最多16），含review及底层重试；实例单HTTP尝试、输入/输出与wall-time都有界，所有成功/失败usage保留。已发送未知费用不记零。
- 任一步未完成均保留实际诊断，不把模型组件或合成fixture拼成全链通过。

## 分工
- Pauli：unused supplemental恢复代码/schema/测试，不操作真实库或联网。
- Pascal：C-only gzip/header/完整性测试，不操作真实库或联网。
- D harness implementer：真实首稿模式与出处核验，禁止fake初稿冒充真实。
- C operator implementer：本轮私有部署准备；主会话独立批准后才实际操作/GET/自动准入。
- 主会话：协调/纠偏、独立检查、真实模型执行、账单usage记录与最终验收。

## 后续独立许可：大正文最后一次有界取源

390纠正后的新派发已实际发生，但在30秒fetch deadline内终止unknown；不可使用390去撤销已消费授权，更不能重开该dispatch。原始链现在有两条实际registered attempt，均unknown并保守按已消耗计。

后续单次、单独记录的无HTTP诊断显示DNS、B签名和TLS正常；另行批准的一次HEAD返回200、Content-Length2033807、无Content-Encoding，约0.9秒到header。HEAD不是capture；这些后验事实不能证明此前具体超时子阶段，但支持对大正文时限作有界验证，而非继续盲目30秒重试。

依据既有项目政策允许必要失败重试/技术参数调整，且用户本轮明确要求真实全链，主会话将新增**独立、显式的最后一次取源许可**，不是复用已消耗权利：同一原始链累计registered派发硬上限3，现有2个unknown不清零；单原始链只能有一个final-followup allowance，仅授予一个新精确dispatch/request/policy/root。保持同库、同URL/Subject/版本/用途/8MiB，旧350/390权利和审计行不改，不能自动再发第四次。

400只实现受信operator显式授额端口及数据库guard，无公共路由/自动循环。新的长正文时限仅用于正式C full GET，最多300秒；B的FetchLimits最大30/默认值不变，signed grant TTL仍4秒，C一次性completion窗口有界匹配长fetch。附带安全阶段/字节计数诊断，不输出正文或秘密。必须独立测试/审阅新许可、代码和实际镜像/隔离后，主会话再次明确live放行，才运行这一笔；本规划不等于已经执行或通过。

## 2026-09-28 用户纠正授权理解后的部署修复执行

第三次派发在签名阶段 EGRESS_UNVERIFIED，已终态unknown，旧400许可耗尽不复活。用户指出已给予项目持续授权，随后明确“执行”。主会话重新核对项目政策第8-13/34行：新的有界grant和必要重试已在持续授权范围内，无需逐次向用户申请；此前把内部许可耗尽当成缺少用户授权是主会话错误。预算不重置，unknown不记零。

最短修复路径：保持非root零capability worker、signer peer检查和TTL4不变，修正共享net/PID拓扑，并先在无外网独立测试身份下验证完整真实签名交互及负例，不再以静态哈希/配置检查代替功能验证。版本化最小迁移复用现有allowance/auth表，仅另行追加一次绑定部署修正的gen4许可，旧行不变，同URL总派发硬上限4，禁止第5次或自动循环；不新增通用授权框架或修改已签发gen3授权。必须经过新grant合同独立检查与实际部署功能预检，主会话才执行此新许可。源抓取成功后立即接现有自动审核准入及真实D首稿/后继稿，不扩写结束语约束、不提交发布。此段是新执行计划，不追改前三次许可范围或伪造历史成功。

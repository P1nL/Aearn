# 真实首稿 → 真实修订验收入口交接

> 用户指定的 `live-parent-plan-20260928.md`；本机 `Get-Date -Format o` 本轮实际返回 `2026-09-28T00:07:17.4939595+08:00`。这里是有界 harness 实施/离线测试记录，**不是实际模型或来源成功验收**。

## 本轮写集

仅 `aearn/infra/rag-d-live/`、其 focused tests、本报告及 README。没有修改 app/schema/语义策略、没有提交。新增 `real_parent.py` 和 `parent_provenance.py`，扩展 `prepare.py --real-parent`，在 `run.py` 消费首稿证明。保留原 fixture 模式并继续明确标记 `test_owned_fixture`。

## 独立全局 runtime gate 前检（追加；未对 live 库执行）

正常 `prepare.py --real-parent` 只读取 server capability，不能暗中启用 DB cutover。当前 live 库 GET 能力此前为 false 的场合，在**当前有效 C 准入完成后**，主会话单独操作一次 `runtime_preflight.py`，不是改 SQL 字段。必须确认：本次 C root config 与只读私有 DSN 的库名一致、实际连接 `current_database()` 精确等于 fresh `aearn_rag260_c_d_*`；没有混用旧 live/fixture/业务库；root-owned config/DSN 无 symlink、私密权限且只读挂载；该次进程只在隔离 PG 网络，无 provider JSON/密钥、无公网或 C worker egress。不要从历史过期 grant/未知尝试推断来源准入。用户 Harness cutover 与这个全局 gate 是两件事。

```sh
PYTHON_DOTENV_DISABLED=1 LLM_TYPE=disabled python -B /workspace/aearn/infra/rag-d-live/runtime_preflight.py \
  --execute --control-config /etc/rag-c-control/config.json \
  --database-name "$FRESH_C_DATABASE_NAME" --operation-id "$UNIQUE_OPERATOR_INVOCATION_ID"
```

不带 `--execute` 必须在文件/DB IO 前拒绝。该脚本只用真实 `TutorThreadTurnCutoverService.dry_run → prepare(expected_generation, idempotency_key) → enable(expected_generation, exact summary_hash, idempotency_key)`，审计本代 preparing/preflight/enabled；已启用时只核验、不重写。拒绝非空 legacy 工作、库存依赖缺失、错 DB、失配 config/DSN、zero/fake hash、过期 generation；失败回滚且不能以 fixture 结果替代 live 前检。输出是内部 operator 身份/摘要/调用数0，不是 C 授权、来源成功或 D 成功。

该实现在**本代理**只于新建 WSL `127.0.0.1:55438`/`aearn_d` 的 `aearn_rag260_c_d_gatefixture_01a0e67a` 测试库执行完整 manifest 双 bootstrap 与实际 owner 测试：17 passed（14 offline + 3 PG）。没有运行真实 C 库或 provider；测试库只是控制语义证据。后续由主会话 fresh C admission 后按 live DB 当前配置单独执行，核验 public effective capability，再运行以下真实首稿/修订；模型首稿<=8 HTTP、修订<=8 HTTP，累计上限16；实际 usage 逐次记录，未知费用为 unknown/null 非0。

## 主会话精确执行顺序（尚未执行）

先由主会话核实同一 disposable C DB 中**当前有效** capture → trusted service review → admission → partial corpus 已完成；原 unknown/到期回执不够，新 supplemental/revoke/GET 操作全部由来源 owner/主会话控制。本入口不抓取、不签发来源批准、不更改来源历史。

使用已有 pinned D-only image 和 README 的七个只读源码挂载。root-owned C config/DSN/receipt/public key 均是本次有效输入；provider JSON 仍仅通过 stdin/private rootfile 提供。非秘密 flag `RAG_EVIDENCE_CONSUMER_ENABLED=true` 必须在每个 exec 中显式设置，不能把真实秘密放 Docker argv/Env/image。

```sh
# 阶段 P：普通真实 Primary gateway 创建首稿；最多两轮 learner input。
RAG_EVIDENCE_CONSUMER_ENABLED=true python -B /workspace/aearn/infra/rag-d-live/prepare.py \
  --execute --real-parent \
  --control-config /etc/rag-c-control/config.json \
  --provider-config /run/d-live/provider.json \
  --parent-provenance-out /run/d-live/parent-provenance.json \
  --wall-seconds 240

# 阶段 D：只用阶段 P 返回的真正首稿/target IDs；必须提供其证明文件。
RAG_EVIDENCE_CONSUMER_ENABLED=true python -B /workspace/aearn/infra/rag-d-live/run.py \
  --execute --parent-kind real_provider \
  --parent-provenance /run/d-live/parent-provenance.json \
  --provider-config /run/d-live/provider.json \
  --control-config /etc/rag-c-control/config.json \
  --receipt /run/review/NEW_RECEIPT.json --service-public-key /run/review/PINNED_PUBLIC.raw \
  --capture-id NEW_CAPTURE_UUID --corpus-id NEW_CORPUS_UUID --admission-run-id NEW_ADMISSION_RUN \
  --user-id P_USER --session-id P_SESSION --conversation-id P_CONVERSATION \
  --parent-draft-id P_DRAFT --target-run-id P_TARGET_RUN --target-input-revision P_TARGET_REVISION \
  --max-http 8 --draft-output-tokens 4096 --input-limit-tokens 8192 --wall-seconds 240
```

路径中的 NEW/P_* 必须替换为本次真实输出，不能照字面运行。real-parent 模式禁止与 fixture DB 参数混用。首稿 proof 文件 O_EXCL、0600、root-owned；已存在则拒绝覆盖，不自动重跑收费首稿。应在容器退出前将不含正文/密钥的私有 audit 按现有证据政策保存，不能丢失后靠 CLI label 重建“真实”结论。

### 真链执行前逐项确认（主会话，不是本代理的测试结果）
1. 新 C 准入与 root/review/retention 当前有效，capture、review、admission、partial active corpus 均在同一 fresh live 库；旧 unknown attempt 不回放，不从 fixture 复制来源或 parent。先按上述独立 preflight 核验并启用全局 gate，再让首稿的 public API 实际读到 `effective_enabled=true` 及用户 Harness `verified`；否则停止，provider 请求0。
2. 重新核对本次 D-only image digest、七个窄只读源码挂载（API app、API tests、worker、shared packages、C control、C live、D scripts）；只读挂载本次 C config/DSN、签收 receipt 和 review 公钥；root 私有输出区为 tmpfs/0700。不挂整个 repo、Docker socket、业务卷、C worker egress 或旧过期 receipt；旧 image pin 需按当前文件核对而非盲用。
3. provider JSON 由操作者从 stdin 导入 0600 root 私有文件，**不**通过 Docker argv/环境/镜像层写密钥；预检容器不挂载/读取此文件且只有内部 PG 网络。首稿/修订隔离进程才打开限定模型目的地与内部 PG 的网络，失效/失败不扩容重试。事先确认未收到用户停止或已知预算耗尽信号；费用账单由用户监控。
4. 两阶段分别 `--execute`，首稿返回真实 `parent_persisted` 和完整 DB provider receipts/不可重写 proof 后才能原样使用其 ID 调修订；修订保留同 C 精确用途与权威 fence。每阶段最多8 HTTP、总计最多16，usage/失败次数如实留档；未返回用量记 unknown/null，不写0。不可剪改模型计划、改名 fixture、手填 zero summary hash 或直接 SQL 改 cutover/计划/binding；失败按实际阶段报告，不声称全链通过。


## 真实首稿行为和界限

- 用户、session、input 通过现有公开 API 建立；只临时延迟 route 自动 dispatch，然后调用普通 `TutorInteractiveRunDispatcher → PrimaryTutorProviderGateway → OpenAICompatibleClient`。不提供预写 plan JSON，不直接写 draft/selection/binding，不替换真实模型决策。
- 与旧 fixture helper 不同：real 模式不调用会手填 thread-turn cutover 的 `create_tutor_user`。它只调用 `/api/users`、读取 `/api/harness/cutover` 和 `/api/tutor/capabilities/thread-turn-v2`，要求真实现有 runtime gate 就绪；缺失时 `PARENT_RUNTIME_GATE_NOT_READY`、provider 0。主会话需使用现有 cutover owner 正常流程，不手填 zero hash。独立 runtime preflight 仅处理数据库的全局 thread-turn gate；用户 Harness cutover 仍需现行 owner 正常验证。
- 声明合成学习者已掌握 tables/columns/types/CREATE TABLE，仅需要基于既有 SQLite 表学习 WHERE/LIMIT；每周240分钟、beginner 查询、English examples/practice。请求**一个模块、一个 core `sql.queries` 节点、无课内前置依赖**。`CompactPlanModule` 当前允许一个 node（离线合同测试）。模型真实编写 profile/plan prose；如仍生成别的节点、schema prerequisite、多模块或无法落稿，记录失败，绝不剪裁/改写输出换取通过。
- 全部七项 learner facts 作为 API `planning_facts` 输入，而非伪造 server facts。最多一次追加澄清，重复同一声明，不读取模型提问去杜撰答案；两次输入仍无稿就停止。provider 不可用/预算耗尽/错误状态不发第二次输入重试。
- 为避免把 immutable learner pace 误当可自由编辑字段，首稿后的 target input 通过现有 `reopen_fact_fields=["pace_constraints"]` 明确允许依据教材缺口调整 pace；核心目标/节点/240分钟不变。并非绕过服务端事实校验。
- 初始普通首稿本身不授来源 ready。版本来自严格解析的 operator-locked C scope，而不是硬编码 v1 或推测 active pointer；修订阶段在模型调用前校验同一 corpus 的精确 subject/version。课程只请求 queries 不代表整个 SQL 来源池完整：最终仍输出 C 全局 `schema` gap 和 main-teaching 缺口，仅允许 supplementary 绑定。

## 实际 provenance 检查（不是调用者自报 flag）

1. Parent stage 计数真实 urllib POST，每个实际 client 实例 `max_http_attempts=1`；禁 redirect，防止隐藏第二次 HTTP。root audit 记录请求 facts hash（不含全文）、配置 model/实际 response model、每次 usage/unknown、run/revision、parent ID/content hash、source scope、provider receipt IDs/安全字段。
2. 只有普通 loop 完成、确有 capability 调用、数据库首稿 version=1 且无 predecessor、精确 pilot shape、实际 HTTP>0 且 <=8 时才可生成 `parent_persisted` 证明。
3. 必须对同 user/conversation/run/revision 读取 `tutor_provider_attempt_receipts`，数量与真实 HTTP/client calls 一致，model/provider/accepted 原始记录匹配；不存在或错 scope 拒绝。provider 返回实际 model alias 与配置别名分别保存，不将别名推断为 provider 实测。
4. 修订入口 `--parent-kind real_provider` 缺 `--parent-provenance` 会在 I/O 前拒绝；加载安全 rootfile 后重验当前不可变 draft 坐标及数据库 receipt 内容。fixture 不能仅改 label 变真实。此文件是可信 operator 本次传输记录，不宣称是供应商签名证明，也不是来源授权。
5. 修订继续使用实际 D feedback/context/capability/fence；同一个 counted client 同时供 drafting 与真实 semantic reviewer 使用。成功输出额外核验 settled/consistent semantic rows 及其 accepted provider receipt，且 reviewer model 在本次观察到的 response models 中；精确绑定仍重验当前 C 权限。

## 成本/时间/privacy 硬界限

- 首稿阶段固定最多8 HTTP，含两轮输入和 gateway repairs；修订阶段最多8 HTTP，含 semantic review 和 repairs。**整条声明上限16**，成功输出实际父/子/合计次数，不能只宣称8总计。
- 首稿4096 draft-output /8192 input，review仍256；修订命令同值。两阶段各240s wall（允许既有30–300范围）。signal 的固定安全异常不被普通 gateway Exception 修复吞掉；服务端已收到的请求仍可能计费，unknown 不当0。
- 从 audit/输出排除 DSN、API key、源正文、完整模型提示/响应和 learner 内容。只有 bounded IDs/hash/count/model/usage/gap status。没有新增服务，没有修改产品默认预算或模型设置。

## 离线验证及未执行项

- `uv --directory aearn/services/api run ruff check ../../infra/rag-d-live`：passed。
- 本地 focused pytest：33 passed；pinned D-only image `sha256:5b91e22aa3d1a436a3fc121b44374d89ae01e54c14459035d9af3faa462ca2b4`、`--network none`、七个只读挂载：33 passed。compileall：passed。
- fake 测试明确只证明控制逻辑：双 opt-in、单/双输入边界、model failure不隐式重跑、单节点当前合同、错误prerequisite拒绝且原JSON不变、真实label缺proof拒绝、错draft/version/receipt/次数拒绝、model alias观察匹配、redirect拒绝、wall异常不被修复吞掉。
- **本实现者真实 provider=0、source fetch=0、C/业务PG执行=0（本次真实首稿slice）**。尚无实际 real-parent proof、真实首稿→修订结果，不能将33条fake/offline测试当全链通过。主会话按来源和真实输出分别记录失败阶段；现有 fixture 与此前 PG smoke 仍只是各自原证据等级。

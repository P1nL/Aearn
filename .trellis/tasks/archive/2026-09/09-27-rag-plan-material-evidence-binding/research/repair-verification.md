# D 追加修复验收（2026-09-27）

本文件不替代首批implementation-verification.md，不把旧通过数当成本批次通过。用户授权三项修复；没有commit/push/deploy或公开消费者启用。

## 已核实的根因
1. 原4096上下文测试是过时体积假设：当下完整请求估算能容纳。修复为测量支持的3500拒绝负例＋4096正常正例，并加exact-fit/少1token边界；不是修改生产限额或删除零调用/零写断言。
2. 独立check额外发现真实缺口：gateway追加修复指令后没有重新核算输入预算。新增per-attempt完整消息守卫，最终接线与测试另记，不以纯helper通过代替发送路径验证。
3. 合法JSON的错误含义不能由结构校验、固定免责声明或固定模板证明正确。主会话两次纠偏，拒绝以锁死计划修订能力来回避问题。采用有界独立模型语义审查，保留确定性C授权与目标/用途检查；概率性审查不代表任意自然语言绝对正确。

## 环境与隔离
- 本轮新建WSL PostgreSQL16集群：/tmp/aearn-d-repair-01a0e0c7-zafzy2vf，127.0.0.1:55438。只供本轮专库，无原业务数据。D、budget、check、regression、CLI各专库按真实guard分开，完整schema初始均双bootstrap。
- Docker Desktop初始启动失败，日志涉及Inference/Secrets Engine socket不可访问；随后引擎恢复可用。没有重置Docker或删除全局socket/业务卷。旧C来源与回执仍过期，不能因Docker恢复变当前。
- C provenance/automated review/bridge聚焦：65passed/1skip（Windows non-root Unix peer）；一次误传CLI命名专库被guard拒绝，改用C命名隔离库重跑，未放宽guard。
- 首批67个C/无关基线文件hash再核验：仅既有D共享集成的backend index、schema manifest、schema manifest test、C inventory、database doc五处变化；C业务代码和.codex/config.toml未由本修复改写。

## 最终集成与真实验收
### 已完成的修复与验证

- 真正的概率性教材语义reviewer接入D候选：完整server facts、candidate/public_message/public_thinking_text，closed verdict/reason，不一致进入既有有界重生成；不确定/无效/不可用拒绝。目标与来源权限仍由确定性代码决定，不限制合法计划修订为固定模板。
- 独立check发现的时序/旁路已修复：stream安全校验先于review；append要求匹配的accepted provider attempt；missing-feedback旧稿修订拒绝；exact-attempt replay不重复调用；dispatched→settled用量审计与后续lease/权限资格分开。检查报告给出当前范围无剩余P1，不代表所有自然语言绝对正确。
- 真实组件调用发现JSON模式仅传schema参数不够：首次review返回invalid_response并安全拒绝，随后将合法verdict/reason对明确写进SYSTEM而不放松enum。主会话也发现独立导入循环，保留3个公开导出的lazy package修复及干净进程回归。

| 验证 | 实际结果 |
|---|---|
| 主会话最终全D专项，fresh专库、最终manifest双bootstrap | **59 passed，0 skipped，48.83s** |
| 主会话预算/catalog/context/gateway组合 | **115 passed，8.33s**；dotenv关闭，fake transport显式fake base URL，不依赖本机凭据 |
| 独立最终check reviewer/PG/consumer/schema/gateway | **107 passed，0 skipped**；与其他批次有重叠，不相加为唯一测试数 |
| worker可选deadline配置 | **11 passed，24 subtests passed**；默认10秒不变，显式上限30秒，8MiB/零redirect不变 |
| D-only Linux operator入口离线验证 | **16 passed**；固定依赖镜像、现有API/loop产生fixture首稿，无模型网络出口、无真实provider |
| Ruff app/tests/新增infra | passed |
| Mypy app完整检查 | **326 source files passed** |
| uv lock check/offline、diff check、Trellis validate | passed（仅既有CRLF提示） |
| 主会话最终广回归（全新fixture-only专库） | **1304 passed，55 skipped，282.23s**；skip主要为其他专库/开关/真实Unix peer，另有三套固定库名semantic路由测试未纳入本命令，不称全后端全平台通过 |

较早广回归发现两项inventory遗漏（新增私表及精确semantic读取符号），已补精确例外和负例，未放宽authority扫描。随后复用已含持久化C/D fixture的库导致7项既有空库/generation/清理计数假设失败；保留证据，未改生产CAS或清理审计行，最终改用全新fixture-only专库验证。55项skip及三套固定库名semantic suites的范围不冒称通过。

### 真实模型组件（非C+D全链）

本修复共3笔真实DeepSeek请求：首次schema-contract问题346tokens；修复后错误SQL WHERE→学习地点描述被判inconsistent/facet_meaning_mismatch（443tokens），忠实缺口描述被判consistent/supported（450tokens）。合计**1239tokens**，没有隐式HTTP重试；已追加项目usage登记，人民币费用与余额仍unknown，由用户看账单。第一份失败证据不覆盖，第二份为两个明确正反例，不称自动规划全链重试成功。

证据：`real-semantic-review-controls.json`、`real-semantic-review-controls-2.json`。输入是公开SQL合成事实，没有现时C准入或D持久化；实际自动候选修复和无写入拒绝由隔离PG＋确定性transport测试证明。

### 真实来源与全链未通过

新鲜C环境实际重新做11项网络DROP/非root/Unix/B签名/服务pin预检。首次worker在10秒fetch期限超时，持久保留unknown，是否发送GET未知。第二次、最终一次补充worker配置30秒，但沿用同一policy/generation的operator注册与现行补充派发成功合同不兼容，在DNS/HTTP前被拒绝，没有第二次GET；不是已证实的schema350缺陷。未消费授权不可变，未修改/删除/重绑它，也没有第三次调用或另建root/DB绕行。

因此capture/review/admission/corpus仍全0，**真实当前来源→真实规划模型→D持久绑定仍not_executed/未通过**。新D-only runner、固定依赖镜像和fixture准备已就绪，但没有用合成或过期来源替代真实准入。需独立审阅符合现行合同的来源授权纠正路径后再验收，不能归因为用户未给予联网权限。

### 保留边界与收尾

- 单独生成的`turn_completed`自由文本不在候选语义审查范围；本批次不宣称所有聊天文本均已审查。
- 来源失败证据及所有私有卷保留；主会话已成功停止本轮三个新live control/egress/PG容器，没有删除卷/检查点或停止旧业务容器。全部测试结束后，核对postmaster.pid的实际data目录与55438端口，已成功停止本轮WSL测试集群；其数据目录保留。
- 所有代码仍在当前工作树，默认公开开关未打开，没有commit/push/deploy；任务in_progress，不能把第三项验收写completed。

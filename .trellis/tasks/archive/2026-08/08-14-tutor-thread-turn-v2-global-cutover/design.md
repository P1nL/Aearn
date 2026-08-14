# Tutor thread/turn v2 全局切换：技术设计

## Gate 模型

```text
runtime_v2_enabled = settings.TUTOR_THREAD_TURN_V2_ENABLED
                     AND db_cutover.state == "enabled"
```

环境变量是紧急 kill switch；`tutor_thread_turn_cutovers` singleton row 是跨 API/worker/Desktop capability 的原子 authority。进程不得只缓存 env 后绕过 DB state。

## Singleton 与状态迁移

表保存 `cutover_version` 主键、state、generation、summary_hash、counts_json、block_code、prepared_at、enabled_at、updated_at。operator service 使用固定 PostgreSQL advisory lock：

```text
idle -> preparing -> blocked
                  -> ready -> enabled
blocked -> preparing
ready -> preparing（summary 变化）
enabled -> read-only disabled（通过 kill switch，不回到 legacy）
```

schema state 保持闭合；请求携带 expected generation 和 idempotency key/body hash。

## Preparing 事务边界

进入 preparing 先更新 singleton generation，再让所有 legacy write/dispatch/lease 入口读取该 authority 并 fail closed。随后按 conversation→run 固定锁序小批量 inventory，避免单个超大事务；每批带 generation 与稳定 event key，可重入。

分类：

- waiting_for_input：`status/terminal_outcome=failed`，diagnostic=`legacy_continuation_requires_new_turn`；
- queued/leased/running/waiting_for_capability：`cancelled_at/terminal_at=now`，outcome=`cancelled`，diagnostic=`legacy_protocol_cutover`，清 lease；public serializer 忽略该内部原因并映射为普通 `interrupted`；
- awaiting_effect_commit：只读 proof/receipt，不修改 effect authority；任何 ambiguous 结果写 singleton blocked。

run loop 所有 provider return、capability、effect 和 public message 边界继续检查 cancel/lease/protocol generation，防止 cutover 前已发出的工作迟到写入。

## 旧 POST tombstone

路由在调用 public service 前直接返回 HTTP 410 与 safe envelope：

```json
{
  "code": "TUTOR_LEGACY_CONTINUATION_DISABLED",
  "recoverable": true,
  "next_action": "start_new_turn"
}
```

不得 schedule `BackgroundTasks`，不得写 idempotency record 或读取/修改 run。legacy history/detail/SSE routes 继续通过既有 user scope gate 只读服务。

## Preflight

生成 canonical summary/hash，至少包含：legacy nonterminal counts、active leases、ambiguous effects、v2 schema 版本、worker task/beat 注册、old POST probe、snapshot/history probe、Desktop capability contract version。任何变化使 ready summary stale 并要求重新 prepare。

Enable transaction 验证 expected generation/hash/state=ready，再写 enabled 与审计 event。Desktop 通过 server capability 读取有效 gate，不从本地配置猜测。

## Rollback

kill switch=false 或 DB authority 被运营设置为 read-only disabled 时，v2 writes/dispatch/drain 停止，snapshot/history 保持。旧 POST 继续 410，已终结 legacy rows 不复活。生产数据删除、route 物理移除和恢复旧协议均不属于 rollback。
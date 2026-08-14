# Tutor thread/turn v2 全局切换运行手册

**日期：2026-08-14。** 本手册仅描述本地/运营机制；本任务未执行生产切换。

## 安全边界

- 先备份并确认目标环境；不得在普通测试中对生产运行。
- `TUTOR_THREAD_TURN_V2_ENABLED` 是 kill switch，PostgreSQL singleton 是原子 authority。
- blocked 代表 effect/action receipt 不明确；禁止 force override。
- rollback 不恢复 legacy write，不复活已终结 run。

## 命令

从 `aearn/services/api` 执行：

```powershell
uv run python -m app.services.tutor.thread_turn_cutover_cli status
uv run python -m app.services.tutor.thread_turn_cutover_cli dry-run
uv run python -m app.services.tutor.thread_turn_cutover_cli prepare --expected-generation 0 --idempotency-key prepare-001
uv run python -m app.services.tutor.thread_turn_cutover_cli enable --expected-generation 1 --summary-hash <sha256> --idempotency-key enable-001
uv run python -m app.services.tutor.thread_turn_cutover_cli rollback --expected-generation 1 --idempotency-key rollback-001
```

启用前必须核对 summary 中 `legacy_nonterminal=0`、`active_legacy_leases=0`、`ambiguous_effects=0`，并确认 worker import、schema、410 tombstone、snapshot/history 与 Desktop contract 均 ready。

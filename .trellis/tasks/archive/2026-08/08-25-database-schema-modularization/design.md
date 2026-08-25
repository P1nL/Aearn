# 技术设计

## 目录

建立 `app/db/schema/`，使用带语义名称的 SQL fragment。Python manifest 明确列出顺序并逐个读取执行。目录名或数字前缀只帮助阅读，不作为唯一排序机制。

## 执行模型

`apply_schema(conn)` 遍历 manifest，在同一 connection 上执行每个 fragment；不在 fragment loader 中 commit。seeds 仍在所有 Schema fragment 完成后执行。

## 兼容

若测试或文档需要完整 Schema 文本，提供由 manifest 组合的只读 helper，而不是同时维护第二份聚合 SQL。任何兼容 `SCHEMA_PATH` 的需求必须通过搜索和测试确认后再决定。

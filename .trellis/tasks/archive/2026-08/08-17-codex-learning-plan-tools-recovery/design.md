# 技术设计

## 工具注册

通过 `AgentToolRegistryPort` 向 Codex Runtime 暴露 Aearn-owned tool definition 和 handler。定义与 invocation 均绑定当前 `TutorRunContext`；模型参数只描述业务建议，不描述 authority。

## 工具一：规划上下文读取

输入为空或仅含 schema version。handler 从宿主 context 取得 user、conversation、plan session 和 revision，输出：

- confirmed facts 与 missing facts 的安全投影；
- 当前 draft id/version/hash 和模块摘要；
- facts revision/fingerprint；
- 当前允许的语言、阶段和模块数量约束。

## 工具二：学习计划草案

建议输入：

~~~text
modules[]:
  stable_key
  title
  objective
  estimated_minutes
  prerequisites[]
  nodes[]
~~~

节点 schema 复用或适配现有 LearningPlan domain type。profile、source、user/session、revision、draft version 和 capability policy 全部由 handler 构造。

## 结果模型

`AgentToolResult` 包含 status、safe code、issues、public summary、receipt/idempotency 信息。`repairable_invalid` 作为正常 tool output 返回 Codex；transport exception 仅用于真正的 protocol/runtime failure。

Issue 只暴露 allowlisted code、JSON path 和修复提示，例如模块数量、缺失字段、重复 key、prerequisite cycle；不回显完整 raw value。

## 修复循环

1. Codex 调用 draft tool；
2. handler 完成 schema/domain/fence 校验；
3. 可修复时返回 issues 和剩余 repair budget；
4. Codex 在同一 Turn 重新调用；
5. 成功 append draft 后返回 immutable receipt；
6. 超预算或非修复类错误由 Runtime dispatcher 结束 Turn。

## 一致性

写入使用 active session lock、facts revision 和 idempotency key。断连发生在 commit 后时，重放通过 receipt 返回原 draft，不再次 append。任何 stale generation 的 late result 只记录 ignored/conflict，不影响当前 plan。

## 兼容策略

保留现有 Harness capability contract 供旧 Runtime 使用。本任务新增 typed tool facade，可在后续 cutover 稳定后再单独决定是否收敛旧 `profile_json/module_N` 接口。

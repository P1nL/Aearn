# 类 Codex Tutor Desktop 与集成迁移验收：技术设计

## 前端状态模型

新增 conversation controller/reducer，以 server snapshot 为初始 authority：

```ts
type TutorConversationState = {
  snapshotVersion: string;
  controlVersion: number;
  streamCursor: string | null;
  activeTurn: TutorTurnSummary | null;
  controlState: TutorControlState;
  pendingRequest: TutorRequestItem | null;
  queue: TutorQueuedInput[];
  itemsById: Map<string, TutorPublicItem>;
  orderedItemIds: string[];
};
```

reducer 只接受 typed snapshot/event；sequence <= current 时忽略，gap/version mismatch 触发重新 snapshot。网络 loading/error 与 server domain state 分离。

## 页面结构

```text
Header / conversation controls
Timeline scroll region
  learner message
  tutor message + optional Think disclosure
  request / error
Queue tray（仅有 pending queue 时）
Composer / targeted response controls
```

Queue tray 在 composer 上方，不占据独立 dashboard。每项提供编辑、上移、下移、立即执行、删除；移动按钮有明确 accessible label。timeline 自身 `min-height: 0; overflow-y: auto`，composer 不随历史滚走。

## 输入区状态

- `idle`：主按钮“发送”。
- `running`：主按钮“加入队列”，secondary menu“引导当前处理（Steer）”，旁边 Stop。
- `waiting_for_input`：显示目标问题与“提交回答”；secondary“作为后续问题加入队列”。
- `waiting_for_approval`：批准/拒绝 typed controls，不把自由文本当 approval。
- `failed_recoverable`：保留普通 composer并显示 Retry card。

Steer 不设置隐藏默认快捷键；键盘用户通过可聚焦菜单触发。提交 mutation 时携带 snapshot 的 expected IDs/version；409 conflict 后重新 snapshot并保留未提交 draft。

## 时间线与公开 Think

`TutorPublicItem` 使用 discriminated union exhaustive handling，但 renderer 对独立 `process` item 返回空显示并继续维护 sequence/cursor。Tutor message 的 `public_thinking_steps[]` 非空时渲染 DSH-derived `Think` disclosure；展开状态按 message item ID 保存在组件内，不进入持久化 storage。正文只使用后端 learner-safe steps；前端不读取 process steps、tool/category/raw event 或 provider reasoning。

error card 根据 public `actions` 渲染 Retry/重新发送/稍后重试；内部 diagnostic 不显示。Interrupt 使用中性终态，不渲染成系统故障。

## 事件流与恢复

`useTutorConversationStream`：

1. Abort previous snapshot/stream；
2. fetch snapshot；
3. hydrate reducer；
4. subscribe after cursor；
5. heartbeat 不改变 state；
6. reconnect exponential backoff；
7. cursor invalid/gap → close stream → refetch snapshot。

离线期间 Queue 自动运行依赖后端 worker；前端恢复时只读 snapshot，不重发 Queue 或 dispatch。

## 迁移

- `api.ts/types.ts` 添加 v2 contract；删除或隔离旧 continuation write helper，使任何 Tutor surface 都无法触达 `/runs/{id}/inputs`。旧 history/run/SSE read methods 可保留。
- `TutorConversationSurface`/相关 page 切换到 v2；feature gate 未就绪时只显示 unavailable/read-only，禁止 silent fallback 到 `/runs/{id}/inputs`。
- 旧 history item adapter 只用于显示 legacy message/process，不赋予继续、Queue、Steer/request 新能力；`TUTOR_LEGACY_CONTINUATION_DISABLED` 仅刷新为只读迁移状态，不自动重试。snapshot 中的 `TUTOR_LEGACY_CONTINUATION_REQUIRES_NEW_TURN` 渲染迁移卡，并把焦点引导到普通 Composer；不预填或提交旧问题的回答，不渲染 approval/authority action。
- terminal diagnostic `legacy_protocol_cutover` 只用于后端审计；public adapter将对应active cancellation归一为普通 `interrupted`，复用Stop后的timeline/control renderer，不生成专用error card或自动动作。
- Desktop capability bootstrap 只接受全局 `thread_turn_v2=enabled|disabled`；disabled 时保留 history read 并统一禁用 writes，不维护 per-user/per-conversation protocol branch。
- 受保护 HTML 原型只作为视觉边界参考，不修改/删除。

## 可访问性与响应式

- 所有 Queue/Stop/Retry/request controls 为原生 button/form control；错误和状态变化使用合适 live region，避免连续进度刷屏。
- 触控目标、焦点顺序、Escape/Enter 行为、disabled 原因清晰。
- 窄屏 Queue action 可换行/菜单化但功能不丢失；reduced motion 禁用非必要展开/状态动画。

## 集成证据

在 `docs/qa/acceptance-test-plan.md` 记录 fixture、命令、结果和残余风险；不记录 learner raw content/provider body。至少用 fake provider 走：fresh turn → request → fresh answer turn → Queue offline drain → reconnect → Steer → Interrupt → Retry。

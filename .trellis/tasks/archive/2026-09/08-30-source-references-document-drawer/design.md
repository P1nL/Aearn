# Source References and Document Drawer 技术设计

## Boundary

复用现有Lesson source/context reference authority，为对话和工件提供exact来源定位、右侧文档栏与窄屏覆盖抽屉。

本 child 不拥有父任务中分配给其他 child 的业务 authority，不得为了局部便利复制 Artifact、Attempt、Teaching、Markdown、Result 或 Item Bank 状态机。

## Architecture

- SourceResolver服务端校验exact scope并返回bounded public ref
- Desktop DocumentDrawer由stable block data attribute定位
- HighlightLayer使用Resize/Intersection观察目标rect，不修改document node边框
- 桌面侧栏和窄屏overlay共享同一document state

## Data Flow

1. citation click -> open drawer -> fetch exact version -> locate block -> scroll -> highlight
2. new citation while open -> reuse drawer并定位
3. collapse -> restore trigger focus

## Contracts and Invariants

- 引用绑定document/version/block/hash，不按文本或DOM顺序猜测
- 点击后只滚动右栏，不改变对话位置
- highlight用overlay/pseudo-element不reflow
- narrow drawer覆盖右侧大部分，外部点击不关闭，按钮/Escape关闭
- 关闭后焦点回来源触发点，Artifact/Editor/Preview不重载
- reduced motion即时定位+静态虚线框
- 完整文档仍在右栏，工件只显示必要引用chip/摘录

## Affected Surfaces

- message/artifact reference contracts/API parser
- LessonSourcesPanel/right document panel
- ArtifactSourceReferences组件
- document drawer styles/animation/hooks
- reference scope/API/Desktop tests

## Compatibility

- 保持现有历史数据和旧 contract 读取；新行为通过 additive version/feature gate 引入。
- 所有未知 enum、extra field、stale identity、跨 scope 和受保护内容 fail closed。
- 不从历史归档恢复已移除 runtime，也不删除受保护前端原型。

## Security and Privacy

- 公共 API/SSE/Desktop/日志/导出不得包含完整 submission、private rubric/test、reference answer、provider body/reasoning、命令、路径、容器或 secret。
- 前端不能把本地 UI state 当作业务 authority。

## Rollback

- 关闭artifact引用入口，保留现有Lesson source panel
- 无法解析时不做文本搜索fallback
- 不删除历史引用snapshot

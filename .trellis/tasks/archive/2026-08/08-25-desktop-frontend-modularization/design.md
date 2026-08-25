# 技术设计

## API 与类型

建立 `src/api/` 和 `src/contracts/`。基础 request/validation 工具与业务域 endpoint 分离；旧 `api.ts`、`types.ts` 暂作 barrel，随后根据 import 收敛结果决定保留或删除。

## 样式

建立 `src/styles/`：基础 token/reset、应用 shell、通用布局、响应式规则。Feature 特有样式迁移到 feature 目录，优先使用 CSS Modules；全局类只保留跨页面 shell 和既有必须共享的语义类。

## Tutor Surface

保持顶层组件作为 composition boundary，把状态推导和动作组织提取到 hooks/controller，把时间线、header、composer、queue/interaction 区域和辅助面板拆成子组件。SSE hook 和 API contract 不在 UI 子组件中复制。

## 兼容

使用 TypeScript barrel 保持导入稳定；每次拆分后运行 focused Vitest 和 typecheck，最后运行完整 Desktop gate。

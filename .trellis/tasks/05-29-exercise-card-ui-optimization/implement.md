# 练习卡片 UI 优化 — 实施计划

## 执行顺序

### Step 1: CodeEditor 自定义深绿主题

- [x] 在 `CodeEditor.tsx` 中通过 `monaco.editor.defineTheme('aearn-dark', {...})` 注册自定义主题
- [x] 色板：背景 `#1a2b23`、前景 `#e4ece4`、关键字 `#5cc9a0`、字符串 `#b8d4a8`、注释 `#5e6b62`、光标 `#2f7d63`
- [x] 编辑器使用 `theme="aearn-dark"`
- [x] 验证：Monaco editor 渲染为深绿色调暗色背景，与项目整体风格协调

### Step 2: ExerciseWorkbench JSX 结构重组

- [x] 左栏：题面 + 空缺填写（紧凑行） + 代码编辑器
- [x] 右栏：运行输出、提示、错误解释、提交摘要集中为结果面板
- [x] 空缺填写从 grid 改为水平紧凑行
- [x] 等效完成：辅助操作（提示目标/层级/获取提示/解释错误）收纳在编辑器下方 tabs 和 toolbar 中，而不是 `<details>`
- [x] 等效完成：解释关键代码 + 检查焦点 + 检查解释收纳在编辑器下方 tabs 中，而不是第二个 `<details>`

### Step 3: 样式重写

- [x] `.exercise-grid` 改为 `.wb-split` 固定高度分栏，右栏结果面板 `overflow-y: auto`
- [x] 编辑器区域：暗色背景圆角容器 + 微阴影
- [x] 主操作按钮区：视觉突出，放入编辑器工具栏
- [x] 辅助操作区：次级视觉权重
- [x] 空缺填写：紧凑水平排列
- [x] 响应式 ≤1180px 回退单栏

### Step 4: 验证

- [x] `pnpm --dir .\aearn desktop:check` 通过
- [x] 验证运行测试、提交、提示、解释错误、检查解释功能保留在同一 workbench 中
- [x] 验证响应式布局切换对应 CSS 已覆盖 ≤1180px
- [x] 验证暗色编辑器在浅色主题中视觉协调

## 回滚点

每个 Step 完成后可独立回滚：
- Step 1: 恢复 CodeEditor 默认主题
- Step 2: 恢复原始 JSX 结构
- Step 3: 恢复原始 CSS 块

# 实施计划

1. 读取 frontend 相关 specs 和当前未提交 diff。
2. 建立 API client 与按域 endpoint 模块，迁移 `api.ts`。
3. 建立按域 contract 模块，迁移 `types.ts`。
4. 拆分全局样式并保持加载顺序。
5. 拆分 Tutor Conversation Surface，更新相邻测试。
6. 搜索旧 import 和重复类型/样式，完成兼容收口。
7. 运行 focused 与完整 Desktop 验证。

## 验证

```powershell
pnpm --dir .\aearn\apps\desktop test -- --run
pnpm --dir .\aearn desktop:check
git diff --check
```

## 实施结果

- 已完成 API、contract、样式和 Tutor Conversation Surface 的兼容式模块化。
- 当前用户新增的侧栏折叠、紧凑 Composer、滚动条和相邻测试完整保留，并由自动化与浏览器回归覆盖。
- 未改变 API/SSE contract、交互文案、焦点语义、响应式断点或服务端权威边界。

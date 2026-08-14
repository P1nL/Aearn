# 实施计划

## 前置检查

- [ ] 加载 `trellis-before-dev`，读取 frontend specs、父任务 PRD/design/research 和本 child 工件。
- [ ] 确认固定 DSH revision 与目标源文件路径。
- [ ] 检查 Desktop package/lockfile，使用现有包管理方式增加测试依赖。

## 实施

- [ ] 新增 `aearn-light.css` 和 scoped `dsh-compat.css`。
- [ ] 派生 Button/Pill/Input/StateDot/DisclosureRow/Tooltip/MessageText 及 CSS modules。
- [ ] 只派生实际需要的非品牌 icons。
- [ ] 使用 sonner 建立 toast 外观 adapter。
- [ ] 建立 `index.ts` 公共 export，确保无业务依赖反向导入。
- [ ] 新增 `THIRD_PARTY_NOTICES.md`、`UPSTREAM.md` 和来源注释。
- [ ] 配置 Vitest/Testing Library/jsdom 与 Desktop `test` script。
- [ ] 添加 primitives、token 和 import-boundary 测试。

## 验证

```powershell
pnpm --dir .\aearn\apps\desktop test
pnpm --dir .\aearn desktop:check
git diff --check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-13-dsh-derived-ui-foundation
```

## Review gate

- [ ] 无 Cordis/DSH runtime production dependency。
- [ ] 无 DeepSeek brand asset/export。
- [ ] derived scope 之外不暴露 `--dsw-*` 公共 API。
- [ ] 不修改 Tutor 业务行为或删除旧 CSS。

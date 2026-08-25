# 实施计划

1. 重新核对相关 Git diff，确保不覆盖当前用户修改。
2. 更新 backend/frontend directory spec 和索引。
3. 更新 `aearn/README.md`、API README。
4. 移动 `docs/current/Aearn` 到 `docs/archive/2026-06-18/current-state-audit/`，修复当前文档引用。
5. 删除被跟踪的 desktop `package-lock.json`，更新忽略规则。
6. 取消跟踪 Obsidian workspace/plugin data 并更新忽略规则，保留文件在本地。
7. 验证 pnpm lock、文档链接、Git 状态和差异格式。

## 验证

```powershell
pnpm --dir .\aearn install --lockfile-only --frozen-lockfile
git grep -n "docs/current/Aearn\|current/Aearn/"
git ls-files .trellis/tasks/.obsidian
git ls-files aearn/apps/desktop/package-lock.json aearn/pnpm-lock.yaml
git diff --check
```

## 实施结果

- 已完成目录规范、README、历史文档、依赖锁和 Obsidian 状态治理。
- 未修改产品运行逻辑，未清理被忽略的本地缓存，未提交、push 或部署。

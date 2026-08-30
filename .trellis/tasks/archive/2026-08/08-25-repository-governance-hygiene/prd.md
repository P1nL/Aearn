# 仓库治理与卫生优化

## 目标

让仓库导航、Trellis 结构规范、依赖锁和被跟踪的工具配置与当前 Tutor Harness 实际状态一致，消除会误导开发 Agent 或持续污染工作树的结构问题。

## 背景

- backend directory spec 仍描述已移除的 `graphs/onboarding/learning/review/notes/tooling` 运行时。
- backend spec 仍把历史实施计划作为 current milestone 入口。
- `aearn/README.md` 与 API README 无法反映当前运行时。
- `aearn/pnpm-lock.yaml` 与 `aearn/apps/desktop/package-lock.json` 同时被跟踪。
- `.trellis/tasks/.obsidian/workspace.json` 与插件 `data.json` 保存本地状态并产生无关修改。
- `docs/current/Aearn` 是 2026-06-18 的旧运行时快照，但目录名仍暗示 current。

## 需求

1. 更新 backend/frontend directory spec，使其描述当前实际目录和 source-of-truth。
2. 更新 `aearn/README.md` 与 `aearn/services/api/README.md`，提供当前职责、命令和文档入口。
3. 将 `docs/current/Aearn` 的历史快照整体移动到日期归档，并更新所有有效引用。
4. 以 pnpm 为唯一 Node 包管理器，停止跟踪 npm lock，并补充防回归忽略或检查规则。
5. 停止跟踪 Obsidian 的易变 workspace/plugin data；保留确有共享价值的配置与插件文件。
6. 不删除受保护设计原型，不清理用户现有产品改动。

## 范围外

- 不拆分前端或后端产品代码。
- 不清理被忽略的本地缓存、日志、 Cargo target 或 Trellis backup。
- 不改变依赖版本。

## 验收标准

- [x] Trellis backend/frontend 目录规范与当前 Tutor Harness 目录一致，不再要求创建已移除的旧运行时目录。
- [x] backend/frontend 目录索引与结构规范从 `docs/README.md` 路由当前事实，不把历史实施计划称为 current milestone。
- [x] 两个 README 能准确说明当前职责、安装/运行/验证入口和 source-of-truth。
- [x] `docs/current/Aearn` 不再作为 current 路径存在，历史文件进入日期归档且引用有效。
- [x] Git 只跟踪 `aearn/pnpm-lock.yaml`，不再跟踪 `package-lock.json`。
- [x] Obsidian workspace 与插件个人 data 不再被 Git 跟踪，后续修改不会污染工作树。
- [x] `pnpm` lock 检查、文档路径检查和 `git diff --check` 通过。

## 验证结果

- `pnpm --dir ./aearn install --lockfile-only --frozen-lockfile`：通过，使用 pnpm 10.8.0。
- 历史归档与 README 相对 Markdown 链接检查：9 个文件通过。
- `git ls-files`：只保留 `aearn/pnpm-lock.yaml`；desktop npm lock、Obsidian workspace/plugin data 已从索引移除。
- Obsidian 两个本地文件在取消跟踪前后 SHA-256 一致，用户设置未丢失。
- `git diff --check` 与 `git diff --cached --check`：通过。
- 受保护前端原型仍存在。

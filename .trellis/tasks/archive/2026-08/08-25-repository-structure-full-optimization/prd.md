# 仓库结构全量优化

## 目标

在保留 Aearn 当前 Tutor Harness 产品行为、事务边界、安全约束和用户现有工作树修改的前提下，系统性消除仓库结构中的治理漂移、依赖锁冲突、前端超大入口文件、后端超大持久化模块、扁平测试目录和单体数据库 Schema 维护风险。

## 背景

当前宏观布局“仓库根目录负责 Git、Trellis 与文档，`aearn/` 负责正式运行代码”是正确边界，不做扁平化。结构问题集中在局部：Trellis 规范仍描述已移除的旧 Agent/Graph 目录；Node 同时跟踪 pnpm 与 npm 锁文件；Obsidian 本地状态进入 Git；前端 `api.ts`、`types.ts`、`styles.css` 和 Tutor Surface 过大；Tutor 持久化与 API 测试过度集中；`schema.sql` 缺少有序模块化机制。

## 范围内

1. 完成子任务 `08-25-repository-governance-hygiene`。
2. 完成子任务 `08-25-desktop-frontend-modularization`。
3. 完成子任务 `08-25-api-persistence-test-modularization`。
4. 完成子任务 `08-25-database-schema-modularization`。
5. 在所有子任务完成后执行跨层集成验证和结构审计。

## 范围外

- 不改变 Tutor Harness 的产品语义、公开 API、数据库业务规则或安全边界。
- 不将 `aearn/` 扁平化到仓库根目录。
- 不合并 API、worker、executor 或 shared package。
- 不删除受保护原型 `docs/design/learning-agent-claude-desktop-framework.html`。
- 不提交、push、部署或修改生产环境数据，除非用户另行明确要求。

## 约束

- 不覆盖或撤销当前工作树中的用户修改。
- 每个子任务必须独立可验证；前一子任务完成后再启动下一子任务。
- 文件拆分必须保持现有 import、事务原子性、stale fencing、幂等和安全投影契约。
- Trellis 面向人的任务工件使用简体中文。

## 验收标准

- [x] 四个子任务均完成对应实现和验证。
- [x] 当前 source-of-truth、Trellis 目录规范和实际代码结构一致。
- [x] Node 依赖只保留一个权威锁文件和包管理器入口。
- [x] 前端跨域 API、类型、样式和 Tutor Surface 不再由单个超大文件集中承载。
- [x] Tutor 持久化按职责模块化，原子事务与公开导入兼容性保持不变。
- [x] API 测试按领域组织，完整测试发现数量和结果不回退。
- [x] 数据库 Schema 按确定顺序模块化，bootstrap 可重复执行且数据库契约测试通过。
- [x] 相关 frontend、backend、数据库、lint、typecheck、build 和 Git 差异检查通过。
- [x] 本轮未覆盖用户已有修改，未提交、未 push、未部署。

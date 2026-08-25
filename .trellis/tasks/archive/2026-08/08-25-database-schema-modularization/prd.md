# 数据库 Schema 模块化

## 目标

把难以维护的单体 `schema.sql` 转换为有显式顺序、可审计、可重复应用的 Schema 模块，同时保持 bootstrap、测试数据库和现有数据库业务契约。

## 需求

1. 按基础类型/函数、核心用户与 catalog、Tutor runtime、Learning、Review/Practice、索引与约束等职责拆分 SQL。
2. 执行顺序由代码中的显式 manifest 决定，不依赖目录遍历顺序。
3. 所有 fragment 在调用方同一 PostgreSQL connection 和事务中执行。
4. bootstrap 继续支持重复执行，并保持现有 seed 顺序。
5. 更新测试和文档，不让旧 `schema.sql` 成为双重 source-of-truth。

## 验收标准

- [x] 单体 7000 行级 `schema.sql` 不再作为手工维护的唯一 Schema 文件。
- [x] 存在显式、可测试的 fragment manifest 和顺序校验。
- [x] 空数据库 bootstrap 成功，重复 bootstrap 成功。
- [x] 数据库契约与完整 API 测试通过。
- [x] 不存在 Schema fragment 漏执行、重复 source-of-truth 或隐式自然排序。

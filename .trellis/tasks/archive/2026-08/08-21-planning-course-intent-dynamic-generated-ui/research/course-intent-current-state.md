# 当前课程意图基线

- `language_courses` 当前没有方向 taxonomy 字段或关联表。
- `LanguageCapability` 已维护 canonical IDs、aliases、public course language map 和 selection capability，可用于精确语言归一化。
- 当前语言 presentation 查询所有未归档课程并默认推荐第一项。
- 长期方案必须以 PostgreSQL course-intent relation 为 authority；slug 仅允许一次性 migration backfill，title/description 不得参与 Runtime 匹配。

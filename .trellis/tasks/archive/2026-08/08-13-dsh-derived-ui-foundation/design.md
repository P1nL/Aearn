# 技术设计

## 架构边界

```text
Aearn pages/features
  -> Aearn business adapters
    -> ui/dsh-derived public exports
      -> CSS modules + --aearn-* tokens
```

依赖只能向下；`ui/dsh-derived` 不允许导入 `features/tutor`、`api.ts`、`types.ts` 或 stores。

## 目录

```text
aearn/apps/desktop/
  THIRD_PARTY_NOTICES.md
  src/ui/dsh-derived/
    UPSTREAM.md
    index.ts
    tokens/aearn-light.css
    tokens/dsh-compat.css
    primitives/*.tsx
    primitives/*.module.css
    icons/index.tsx
    feedback/AearnToast.tsx
    tests/*.test.tsx
```

## Token 设计

- `aearn-light.css` 定义 canvas/surface/elevated、border、label、brand、focus、positive/warn/danger、shadow、radius 和 composer geometry。
- `dsh-compat.css` 只为 copied CSS 提供必要 `--dsw-* -> --aearn-*` 映射，并挂在 derived root scope。
- 不在组件里逐处将蓝色替换成绿色；只修改 alias source。
- 保留未来 theme 扩展所需 semantic 层，但首轮只加载 light 文件。

## Component API

- `Button` 使用明确 variants：`primary | outline | ghost | icon`，支持 `busy`、`disabled`、`icon`、原生 button props。
- `DisclosureRow` 受控 `expanded/onExpandedChange`，输出 `aria-expanded/aria-controls`。
- `Tooltip` 使用 portal 或现有可访问实现时不得引入 DSH runtime；disabled target 需要 wrapper/title fallback。
- `MessageText` 只渲染纯文本换行，不引入任意 Markdown/HTML。
- `AearnToast` 只封装 sonner style/class contract。

## 来源策略

`UPSTREAM.md` 每行记录：Aearn path、DSH path、revision、复用类型（copied/adapted/reimplemented）、主要差异。substantial copied 文件头保留短来源注释，完整 license 文本集中在 NOTICE。

## 测试

- Vitest + jsdom + Testing Library。
- 断言 semantics、keyboard、focus、busy/disabled、controlled disclosure、tooltip label、纯文本输出。
- CSS token 测试验证公开变量存在且无 DeepSeek brand token 暴露。
- 静态测试禁止 Cordis/DSH runtime import 和品牌组件 export。

## 回滚

新 foundation 在 Child 4 前不替换现有 Tutor renderer。若 child 验证失败，可移除新增目录、test dependencies 和 NOTICE 增量，不影响现有产品行为。

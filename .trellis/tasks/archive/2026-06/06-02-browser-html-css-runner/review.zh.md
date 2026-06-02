# Browser HTML CSS runner 中文 Review

## 目标

把现有 `browser_preview` 从 `runtime_runner.py` 里的零散启发式逻辑，产品化成独立 browser preview runner adapter。

## 范围

- JavaScript 事件流练习继续检查 `addEventListener`、`output.textContent` 和共享状态。
- HTML/CSS 静态预览练习只检查必需 pattern、blank gate 和 preview assertion，不再强制要求 JS 事件绑定。
- runner 仍然是本地确定性教学 runner，不启动真实浏览器，不安装 npm 包，不联网。

## 验收

- `browser_preview` 仍选择 browser runner，并声明支持 execution/tests/stdout/preview。
- JS event-flow 练习保持原行为。
- HTML/CSS static preview 能在没有 `addEventListener` 的情况下通过。
- runtime error、timeout、hidden redaction 都有稳定测试覆盖。
- Python、Node/TypeScript、SQL、compiled fallback 不回归。

## 关键取舍

- 不做真实 headless browser：当前 child 的目标是合同一致和本地稳定，不是通用浏览器自动化。
- 不执行 `assertion_code`：避免任意代码执行风险，继续使用 server-owned deterministic checks。
- HTML/CSS 与 JS 分规则：避免 HTML/CSS 练习被错误套用 JS counter exercise 规则。

## 实施顺序

1. 补 browser runner tests。
2. 新增 `browser_preview_runner.py`。
3. 接入 registry/runtime dispatch。
4. 跑 focused tests、M3/M4、ruff、mypy、desktop check、Trellis validate、diff check。

## 风险

- 如果现有 JS 练习依赖旧启发式，迁移时要确保 counter-style 行为不变。
- 如果未来要真实 DOM 执行，需要单独任务设计 sandbox/browser dependency，不应塞进本 child。

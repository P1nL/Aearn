# 建立 DSH 派生 UI Foundation

## 目标

从 DeepSeek Harness 固定 MIT revision `47f943859bef60e4160492346772ded9b24f765a` 派生 Aearn-owned 白色浅色 UI foundation，复用选定 primitives、图标、CSS modules 和交互细节，为后续 Tutor Composer、Queue、Question、Think 和 Plan UI 提供稳定底座，同时不引入 Cordis 或 DSH runtime。

## 依赖

- 无代码前置依赖；按父任务 inline 顺序作为第 2 个实施 child。
- 必须读取父任务 `08-13-codex-like-tutor-conversation-experience/research/dsh-ui-reuse-audit.md` 和固定 DSH checkout。
- 不依赖后续 Pending Input、Queue/Stop 或 Tutor integration 子任务。

## 范围内

- `--aearn-*` 白色浅色 semantic tokens 与 derived CSS 内部 compatibility aliases。
- `Button`、`Pill`、`Input`、`StateDot`、`DisclosureRow`、`Tooltip`、`MessageText`、sonner toast 外观 adapter。
- send、stop、queue、edit、delete、check、close、chevron 等实际需要的非品牌 SVG 图标。
- DSH-derived 源码/CSS modules、组件测试基础、第三方 NOTICE 与 upstream mapping。
- 为 keyboard、visible focus、disabled/busy、reduced-motion 和窄宽容器建立基础验收。

## 范围外

- Tutor 业务组件、Queue API、Typed Question、plan inspector 和 run stop 集成。
- DSH `FishLogo`、`BrandWordmark`、DeepSeek 名称、品牌资产和产品文案。
- Cordis、DSH runtime、session、slot、model/access/command 逻辑。
- dark/system theme、主题持久化或 Settings 入口。
- 全局 AppFrame、Sidebar 和其他页面迁移。

## 需求

1. 公共 token 只使用 `--aearn-*`；Aearn 绿色只承担品牌、focus、selection、primary action 和 positive state。
2. 主要 canvas/surface 为白色，保留 DSH 浅色中性层级、边框、阴影、圆角和字体度量。
3. derived components 只接受 typed props/callbacks，不读取 Zustand、Tutor API、session 或 DSH context。
4. substantial derived 文件记录 upstream repository、path、revision 和 MIT 来源；新增 `THIRD_PARTY_NOTICES.md` 与 `UPSTREAM.md`。
5. 不直接安装 `@deepseek-ai/dsh-client-ui-*`、Cordis 或 DSH runtime package。
6. 保留 React 19 类型安全，不用 `any`、`unknown as` 或全局 CSS 覆盖绕过组件 contract。
7. 使用现有 `sonner` 作为通知 runtime，只适配外观；不建立第二个 toast store/provider。
8. 增加 Vitest + Testing Library + jsdom 组件测试能力，并把 `test` script 纳入 Desktop package。

## 验收标准

- [ ] `aearn/apps/desktop/src/ui/dsh-derived/` 形成清晰的 tokens/primitives/icons/feedback 目录。
- [ ] 白色浅色 tokens 和 Aearn 绿色 alias 在独立 fixture 中可观察，未新增 dark/system UI。
- [ ] 所有 primitives 无 Tutor store/API/runtime import，props 和 refs 类型完整。
- [ ] Button/Disclosure/Tooltip/Input/StateDot/MessageText 的 keyboard、focus、disabled/busy 基础测试通过。
- [ ] 图标子集不含 DeepSeek 品牌资产；仓库可见 DeepSeek 产品名称只存在于 NOTICE/upstream 归属位置。
- [ ] `THIRD_PARTY_NOTICES.md`、`UPSTREAM.md` 和文件头来源记录指向固定 revision。
- [ ] `package.json` 不出现 Cordis 或 DSH runtime dependency。
- [ ] `pnpm --dir .\aearn\apps\desktop test` 与 `pnpm --dir .\aearn desktop:check` 通过。

## 风险

- DSH CSS 大量使用 `--dsw-*`；兼容变量必须限制在 derived scope，不能成为 Aearn 公共 token API。
- 直接复制完整 icon 文件会扩大维护面；只复制实际使用的 SVG export。
- 现有全局 CSS 仍服务其他页面，本 child 不做大范围删除。

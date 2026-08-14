# DSH-Derived UI Upstream Map

All entries are pinned to `deepseek-ai/deepseek-harness` revision
`47f943859bef60e4160492346772ded9b24f765a` under the MIT license. Public Aearn
APIs use Aearn names and `--aearn-*` semantic tokens; `--dsw-*` aliases remain
scoped implementation details inside `.aearn-dsh-derived`.

| Aearn path | Upstream path | Reuse type | Main differences |
| --- | --- | --- | --- |
| `tokens/aearn-light.css` | `packages/client/ui-theme/src/styles/design-platform.css` | adapted | Light-only semantic subset with Aearn green identity and `--aearn-*` public names. |
| `tokens/dsh-compat.css` | `packages/client/ui-theme/src/styles/design-platform.css` | reimplemented | Minimal scoped aliases only; no global or dark-theme aliases. |
| `primitives/Button.*` | `packages/client/ui-primitives/src/Button.*` | adapted | React 19 ref support, Aearn variants, visible focus, and busy state. |
| `primitives/Pill.*` | `packages/client/ui-primitives/src/Pill.*` | adapted | Aearn semantic colors and focus/disabled states. |
| `primitives/Input.*` | `packages/client/ui-primitives/src/Input.*` | adapted | Forwarded input ref, invalid state, and Aearn focus treatment. |
| `primitives/StateDot.*` | `packages/client/ui-primitives/src/StateDot.*` | adapted | Aearn state names/colors and reduced-motion fallback. |
| `primitives/DisclosureRow.*` | `packages/client/ui-primitives/src/DisclosureRow.*` | reimplemented | Native controlled button with `aria-expanded` and `aria-controls`. |
| `primitives/Tooltip.*` | `packages/client/ui-primitives/src/Tooltip.*` | reimplemented | CSS-only hover/focus label with disabled-target wrapper fallback. |
| `primitives/MessageText.*` | `packages/client/ui-primitives/src/markdown/MessageText.*` | adapted | Literal text only; no Markdown or HTML rendering. |
| `icons/index.tsx` | `packages/client/ui-primitives/src/icons/index.tsx` | copied/adapted subset | Only send, stop, queue, edit, delete, check, close, and chevrons; no brand assets. |
| `feedback/AearnToast.*` | `packages/client/ui-primitives/src/Toast.tsx` and existing Aearn `sonner` usage | reimplemented | Sonner remains the only runtime/provider; this layer supplies styling and typed helpers. |

Upgrade policy: compare against this exact revision first, review each source
diff manually, preserve the Aearn-owned API, and update this map plus the notice
when substantial derived code changes.

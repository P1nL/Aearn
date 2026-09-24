# A实施验证记录

日期：2026-09-24。A范围实现、独立检查及main最终复跑通过；用户在交付摘要后回复“继续”，本轮按已说明的下一步提交并归档A。代码提交1bbf364，15文件/1354行新增；提交前再次复跑150 passed/7 skipped、Ruff/Mypy281/离线lock通过。B–E未启动，无push。

## 实施前基线（main实跑）

- 当前活动任务rag-material-source-contracts，status=in_progress；初始Git工作树干净，HEAD=57b8661。不制造空checkpoint commit。
- pwsh Core 7；API子目录执行，PYTHON_DOTENV_DISABLED=1、LLM_TYPE=disabled、CODEX_RUNTIME_ENABLED=false，DATABASE_URL指向127.0.0.1:1非业务测试目标。不读取.env，不启动DB或provider。
- subjects、fixtures_v2、corpus_operator_boundary、retrieval_boundary：40 passed。
- sources、fixtures、fetcher、processing、citations、retrieval、retrieval_v2、coverage：34 passed，7 skipped。
- 7个skip均属test_grounding_retrieval_v2.py，要求独占数据库；本任务无数据库接入，因此明确记为未重跑的DB场景，不能当通过。
- legacy-baseline-hashes.json记录43个既有tracked grounding实现/测试文件摘要，供实现后比对。它是兼容性证据，不是生产数据库或联网能力证明。

## 责任分配

GPT-6-Sol implement仅负责autonomous纯合同/策略包、core/config.py四个false配置及新增离线测试。main负责spec、task记录、独立复跑；后续独立GPT-6-Sol check可在相同代码写集修复并补测试。不开启B/C/D，不修改已有fixture、迁移、公开入口或前端。

## 最终实跑（main，独立检查修复后）

- 五个新合同测试文件共76 passed、0 skipped；与74项旧回归合并执行：150 passed、7 skipped，1.72s。7个skip仍全部是上述专属数据库集成场景，不计通过。
- `uv run --no-sync ruff check app tests`：通过。
- `uv run --no-sync mypy app`：281源文件通过。
- `uv lock --check --offline`：55包一致，无联网依赖变更。
- `git diff --check`通过；仅既有tracked文件LF/CRLF提示，不执行renormalize。
- 43个既有tracked grounding文件SHA256全部未变。AST扫描未发现新包被现行app入口导入，也无新包直接网络/DB/process依赖；静态扫描不证明所有动态调用路径。
- 短spec与backend index同步；20个本地索引链接无缺失。子任务implement/check manifests各10条，validate通过。

## 独立检查修复

详见implementation-check.md：用途/完整需求/候选/claim/admission精确关联；独立来源当前文档与family复核；执行方式必须解析单独execution receipt；来源origin/适读性不能被调用方重标；偏好越界拒绝；repo_file两个定位字段必须齐全且其他kind不能携带残缺repo定位。最后一项先复现12个失败，再以32个参数组合覆盖构造与copy旁路。

## AC映射

| AC | A范围证据 |
| --- | --- |
| AC1 | 严格冻结DTO、嵌套copy/construct重验、有界字段与repo/偏好矛盾拒绝：material contracts测试 |
| AC2 | 候选与handle-only evidence分开、偏好不授权限：contract/access/usage测试 |
| AC3 | 受信resolver、完整需求/用途/generation/预算与异常fail-closed：access测试 |
| AC4 | discovery/probe/storage及教学/assessment分层，组合入口拒绝claim旁路：access/usage/claim测试 |
| AC5 | exact claim/document/demand/admission与独立family或单独execution receipt：claim测试 |
| AC6 | 四个false配置及纯判定gate关闭零resolver调用：boundary/access测试 |
| AC7 | 43旧文件hash不变、74离线旧回归通过；7DB场景明确未跑 |
| AC8 | 仅新包/四配置行/测试/短spec；无schema/worker/API/前端接线；Ruff/Mypy/lock通过 |
| AC9 | 本文件/spec明确真实resolver、预算、搜索/准入/评分/发布未实现；旧公开默认保持 |

## 未执行与交付边界

无真实provider/search/抓取/数据库/浏览器/部署调用；不消耗Tavily额度，不读取密钥。未运行全仓pytest或DB集成；A纯合同验证不代表真实语料、Tavily客户端、existing_only回退、题库发布或正式Gate闭环已完成。未自动提交、push或归档；等待独立的提交授权。父计划与研究文件在ignored活动任务目录内，Git工作树清单不能反映这些工件写入。

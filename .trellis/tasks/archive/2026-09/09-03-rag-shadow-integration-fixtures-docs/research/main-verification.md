# 主代理验收进展

- 基线全后端Ruff/Mypy273文件、Desktop tsc/Vite通过；DB与旧Lesson/来源/计划回归92 passed。
- 独立adapter checker发现并修复：真实fixture summary hash缺少两个policy版本；可重算hash的调用方plan必须与服务端重新解析plan一致；新增public consumer隔离扫描。另将child06内部adapter单文件作为旧retrieval import audit的精确例外，其他所有runtime消费者仍禁止接线，并有adapter反向引用扫描。
- 实际demo首跑在任何发布前拒绝（安全JSON DEMO_FAILED）。主代理安全定位为inet_server_addr()::text包含CIDR，ip_address解析失败；已交独立checker修复demo和integration identity SQL，保留demo-initial-refusal.json。不将fake测试通过当作真实CLI演示通过。
- 主代理已在专有demo库写入合成用户/轨道/Lesson失败标记，用于后续demo无学习状态修改取证；不是用户业务库。

## 最终复验

主代理最后联合批330 passed、0 skipped（105.57s）；全app/tests/demo Ruff、Mypy276源文件、uv lock通过，Desktop tsc/Vite复跑通过。实际demo两次80 CLI进程输出一致，161非corpus表不变、回放167表不变；文档根目录命令实际复现同样输出。引用adapter 40真实只读场景、167表及事务指纹不变；10错误目标/开关组合安全拒绝。两个临时库均零连接、无FORCE删除，回执runtime-isolation.json。原业务库未写入，所有GPT-6-Sol子代理完成并关闭。

首次联合批328pass/1fail：LangChain缺失facet按SOURCE_SCOPE_EMPTY提前关闭，无plan；修正integration测试精确断言而非修改retrieval放行。最终批已覆盖修复。早期DB-gated skip不作为验收计数。

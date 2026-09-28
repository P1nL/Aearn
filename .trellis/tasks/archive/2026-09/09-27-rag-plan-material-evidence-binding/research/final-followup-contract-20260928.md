# 最终一次显式 follow-up 配额合同（2026-09-28）

## 审阅检查点：不是390纠错、不是自动重试
主会话明确宣布一笔独立批准的最终 fetch credit：同一数据库、同一原始 attempt 链、同一精确 URL，已经存在的两个 unknown dispatch 均算已消费；本次最多第三个 dispatch。390已消费授权不能撤销或换绑。400只增加一次显式operator allowance及精确授权，未批准真实GET执行，也不触碰live库。

实现方向：immutable allowance唯一绑定original和latest unknown supplemental，generation3新policy/root/dispatch/request/有效期/审批引用；auth增加nullable explicit_followup_id并复用现有ARM协议。原attempt行锁、READ COMMITTED、每original一个allowance、每allowance一个auth及URL计数共同约束。发行/派发前必须正好两个历史attempt；第三次后不增加新机制。400独立trigger先于390/350；400对390发行函数添加仅explicit分支，独立400 trigger负责完整校验；重放390会移除此分支而拒绝新发行，完整manifest400恢复。旧字段值不变，新metadata为NULL。

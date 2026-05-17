import type {
  AppRoute,
  ConversationMessage,
  NavGroupKey,
  SettingsKey,
  SettingsPanel,
} from "../appTypes";

export const ROUTE_META: Record<AppRoute, { crumb: string; hint: string }> = {
  onboarding: {
    crumb: "首次建档 / 实时课程生成",
    hint: "首次使用完成建档后进入学习页",
  },
  home: {
    crumb: "JavaScript DOM / 事件补全",
    hint: "今晚 20:30 继续",
  },
  review: {
    crumb: "复习 / DOM 状态生命周期",
    hint: "复习完成后更新 due_at",
  },
  notes: {
    crumb: "笔记 / JavaScript / DOM 事件补全",
    hint: "Markdown 笔记可编辑",
  },
  settings: {
    crumb: "设置 / 外观",
    hint: "设置影响 Agent 上下文和提醒策略",
  },
};

export const SETTING_PANELS: Record<SettingsKey, SettingsPanel> = {
  appearance: {
    title: "外观",
    meta: "当前版本只展示界面偏好，不直接写后端业务规则",
    cards: [
      ["主题", "奶油色 Claude Desktop 风格"],
      ["内容密度", "宽松，减少学习焦虑"],
      ["动效", "轻量淡入和抽屉滑入"],
      ["侧栏", "默认展开，可折叠"],
    ],
  },
  model: {
    title: "模型设置",
    meta: "说明提示、解释、笔记辅助补全的模型边界；当前不引入未建模的持久化字段",
    cards: [
      ["提示模型", "用于日常代码练习会话"],
      ["测试解释模型", "用于解释失败用例与报错"],
      ["笔记辅助模型", "用于补全当前知识点笔记和结构化总结"],
      ["工具调用", "只在明确需要时启用"],
    ],
  },
  learning: {
    title: "学习偏好",
    meta: "读取并保存当前用户画像与讲解偏好",
    cards: [
      ["讲解风格", "step_by_step / example_then_practice 等"],
      ["鼓励偏好", "direct 等可读写字段"],
      ["职业与背景", "帮助 Agent 控制举例粒度"],
      ["显示名称", "用于本地学习身份和摘要展示"],
    ],
  },
  review: {
    title: "复习",
    meta: "只展示复习优先规则与当前风险摘要，不暴露 FSRS 固定参数编辑",
    cards: [
      ["高风险优先", "最近学习活动超过 72 小时且存在 forget_risk=high 时优先进入复习"],
      ["普通打开", "有 due review 时只提示，不强制跳转"],
      ["后端负责", "due_at、forget_risk、fsrs_rating 仅由后端更新"],
      ["前端负责", "展示提示、恢复入口和复习 notice"],
    ],
  },
  notifications: {
    title: "通知设置",
    meta: "保存提醒开关、时间段和安静时段",
    cards: [
      ["学习提醒", "由 preferred_time_slots 和 reminder_preference 驱动"],
      ["复习提醒", "到期时展示应用内提示"],
      ["安静时段", "quiet_hours 仅影响提醒展示"],
      ["外部通知", "第一版默认只做 desktop channel 描述"],
    ],
  },
  privacy: {
    title: "记录与隐私",
    meta: "展示事实日志和本地内容边界，不允许关闭 Attempt/FSRS 写入",
    cards: [
      ["Attempt 事实", "run / submit / review_submit 继续作为后端事实日志写入"],
      ["复习状态", "ReviewState 和 ReviewLog 不受用户开关控制"],
      ["笔记", "共享知识点笔记仍可本地编辑和导出"],
      ["隐私边界", "当前实现不自动外传本地文件"],
    ],
  },
  diagnostics: {
    title: "关于与诊断",
    meta: "Aearn 桌面端原型信息与本地 API 诊断",
    cards: [
      ["版本", "V1 桌面端原型"],
      ["定位", "代码补全、运行预览、测试判定、复习变体闭环"],
      ["技术形态", "React + Vite + Tauri"],
      ["范围", "当前实现对齐 docs/design 原型结构并补齐 M6 恢复/设置流"],
    ],
  },
};

export const ONBOARDING_MESSAGES: ConversationMessage[] = [
  {
    id: "onboarding-agent-1",
    speaker: "agent",
    label: "Agent",
    text: "先告诉我你想学哪门语言，以及你希望学完后能独立完成什么代码任务。",
  },
  {
    id: "onboarding-user-1",
    speaker: "user",
    text: "我想系统学 JavaScript/HTML/CSS 和一点 Python，能看懂 AI 生成代码、自己补全交互并用测试验证。",
  },
  {
    id: "onboarding-agent-2",
    speaker: "agent",
    label: "Agent",
    text: "我会先把路线拆成 HTML/CSS 基础、DOM 事件、Python 函数测试、AI 生成代码理解、调试小项目五段。右侧会随着澄清实时更新。",
  },
];

export const HOME_BASE_MESSAGES: ConversationMessage[] = [
  {
    id: "home-agent-1",
    speaker: "agent",
    label: "Agent",
    text: "今天先只解决一个问题：点击计数为什么始终回到 1。你先运行可见测试，再根据报错决定下一步。",
  },
];

export const REVIEW_BASE_MESSAGES: ConversationMessage[] = [
  {
    id: "review-agent-1",
    speaker: "agent",
    label: "Review Agent",
    text: "复习不会直接改写今天的学习会话。这里是独立新会话，只追打上一次提交暴露的薄弱点。",
  },
];

export const DEFAULT_NOTE_CONTENT = `# DOM 点击计数

- 目标：把状态变量放到正确作用域，连续点击后输出累加。
- 关注点：事件回调、闭包、测试断言。`;

export const DEFAULT_ATTEMPT_NOTE =
  "Attempt 2：把 `count` 移到事件函数外层，连续点击测试通过。错因：状态变量不能在每次事件触发时重新初始化。";

export const NAV_DEFAULTS: Record<NavGroupKey, boolean> = {
  learn: true,
  review: true,
  notes: true,
  "notes-python": true,
  "notes-javascript": true,
  "notes-sql": false,
};

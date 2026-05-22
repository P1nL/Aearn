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
    hint: "复习完成后更新下次复习时间",
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
    meta: "主题、密度与阅读舒适度",
    cards: [
      ["主题", "当前使用专注学习的暖色桌面主题。"],
      ["视觉密度", "代码、结果和笔记区域保持舒适间距。"],
      ["侧栏", "可通过左上角按钮折叠或展开侧栏。"],
      ["动效", "页面切换保留轻量反馈，减少学习干扰。"],
    ],
  },
  models: {
    title: "模型设置",
    meta: "查看当前模型服务状态",
    cards: [
      ["当前状态", "学习提示、错因解释和笔记辅助会使用本地服务提供的模型能力。"],
      ["解释错误", "运行失败后可以让 Agent 解释原因，并给出下一步建议。"],
      ["密钥安全", "桌面端不会要求填写或显示模型密钥。"],
      ["连接", "通过服务状态确认当前功能是否可用。"],
    ],
  },
  learning: {
    title: "学习偏好",
    meta: "个性化你的学习体验",
    cards: [
      ["讲解风格", "逐步讲解 / 先看示例再练习"],
      ["鼓励偏好", "直接反馈风格"],
      ["职业与背景", "帮助调整举例粒度"],
      ["显示名称", "用于学习身份和摘要展示"],
    ],
  },
  review: {
    title: "复习",
    meta: "查看复习节奏和提醒方式",
    cards: [
      ["今日复习", "有待复习内容时，会在工作区顶部提示。"],
      ["恢复学习", "没有紧急复习时，默认回到当前学习进度。"],
      ["巩固安排", "提交练习后，系统会根据表现安排后续巩固。"],
      ["手动调整", "复习规则暂不提供手动调节入口。"],
    ],
  },
  notifications: {
    title: "通知与提醒",
    meta: "管理提醒时段和安静模式",
    cards: [
      ["学习提醒", "按你设定的时间段推送学习提醒"],
      ["复习提醒", "到期时展示应用内提示"],
      ["安静时段", "在指定时段内暂停提醒"],
      ["通知渠道", "当前支持桌面端通知"],
    ],
  },
  privacy: {
    title: "记录与隐私",
    meta: "查看本地恢复信息和学习记录状态",
    cards: [
      ["本地恢复", "保存必要的学习身份和计划信息，方便下次继续。"],
      ["学习记录", "运行、提交和复习记录由本地服务保存。"],
      ["笔记草稿", "编辑中的笔记会自动保存，减少意外丢失。"],
      ["导出与清理", "后续版本会提供更完整的数据导出和清理入口。"],
    ],
  },
  diagnostics: {
    title: "关于与诊断",
    meta: "版本信息与连接状态",
    cards: [
      ["版本", "V1 桌面端"],
      ["定位", "代码补全、运行预览、测试判定、复习闭环"],
      ["技术形态", "React + Vite + Tauri"],
      ["状态", "查看当前连接和运行状态"],
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
  "第 2 次练习：把 `count` 移到事件函数外层，连续点击测试通过。错因：状态变量不能在每次事件触发时重新初始化。";

export const NAV_DEFAULTS: Record<NavGroupKey, boolean> = {
  learn: true,
  review: true,
  notes: true,
  "notes-python": true,
  "notes-javascript": true,
  "notes-sql": false,
};

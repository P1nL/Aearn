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
    meta: "管理界面显示偏好",
    cards: [
      ["主题", "奶油色柔和风格"],
      ["内容密度", "宽松布局，减少学习焦虑"],
      ["动效", "轻量淡入和抽屉滑入"],
      ["侧栏", "默认展开，可折叠"],
    ],
  },
  model: {
    title: "模型设置",
    meta: "配置学习辅助模型",
    cards: [
      ["提示模型", "用于日常代码练习会话"],
      ["测试解释模型", "用于解释失败用例与报错"],
      ["笔记辅助模型", "用于补全当前知识点笔记和结构化总结"],
      ["工具调用", "只在明确需要时启用"],
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
    meta: "查看复习规则与当前状态",
    cards: [
      ["高风险优先", "中断多日且存在高遗忘风险时优先进入复习"],
      ["普通打开", "有待复习内容时只提示，不强制跳转"],
      ["自动调度", "复习时间和遗忘风险由系统自动计算"],
      ["前端提示", "展示复习提醒和恢复入口"],
    ],
  },
  notifications: {
    title: "通知设置",
    meta: "管理提醒和安静时段",
    cards: [
      ["学习提醒", "按你设定的时间段推送学习提醒"],
      ["复习提醒", "到期时展示应用内提示"],
      ["安静时段", "在指定时段内暂停提醒"],
      ["通知渠道", "当前支持桌面端通知"],
    ],
  },
  privacy: {
    title: "记录与隐私",
    meta: "了解数据记录和隐私边界",
    cards: [
      ["学习记录", "运行和提交记录会自动保存，用于追踪进度"],
      ["复习状态", "复习进度由系统自动维护"],
      ["笔记", "知识点笔记可本地编辑和导出"],
      ["隐私边界", "不会自动外传本地文件"],
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
  "Attempt 2：把 `count` 移到事件函数外层，连续点击测试通过。错因：状态变量不能在每次事件触发时重新初始化。";

export const NAV_DEFAULTS: Record<NavGroupKey, boolean> = {
  learn: true,
  review: true,
  notes: true,
  "notes-python": true,
  "notes-javascript": true,
  "notes-sql": false,
};

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
    meta: "控制桌面端视觉密度和主题偏好",
    cards: [
      ["主题", "奶油色 Claude Desktop 风格"],
      ["内容密度", "宽松，减少学习焦虑"],
      ["动效", "轻量淡入和抽屉滑入"],
      ["侧栏", "默认展开，可折叠"],
    ],
  },
  model: {
    title: "模型设置",
    meta: "配置代码提示、复习变体、错因解释和笔记辅助补全所用模型",
    cards: [
      ["提示模型", "用于日常代码练习会话"],
      ["测试解释模型", "用于解释失败用例与报错"],
      ["笔记辅助模型", "用于补全当前知识点笔记和结构化总结"],
      ["工具调用", "只在明确需要时启用"],
    ],
  },
  notification: {
    title: "通知设置",
    meta: "控制学习提醒和复习到期提示",
    cards: [
      ["学习提醒", "工作日 20:30"],
      ["复习优先", "due_at 到期时优先提示"],
      ["中断恢复", "多日未学时展示阶段摘要"],
      ["外部通知", "第一版默认关闭"],
    ],
  },
  memory: {
    title: "Attempt 记录配置",
    meta: "配置原始 Attempt、测试结果、错因标签和复习状态的保存位置",
    cards: [
      ["原始 Attempt", "保存提交代码、运行输出和测试结果"],
      ["阶段摘要", "按模块生成可恢复练习上下文"],
      ["错因记忆", "绑定掌握度、复习状态和变体题"],
      ["隐私策略", "不自动外传本地文件"],
    ],
  },
  notes: {
    title: "练习设置",
    meta: "控制 Attempt 摘要、自动保存和笔记抽屉偏好",
    cards: [
      ["分类层级", "语言大类 / 练习点"],
      ["自动保存", "编辑时保存笔记抽屉状态"],
      ["默认入口", "当前知识点笔记抽屉"],
      ["导出方式", "仅保留本地 Markdown 笔记"],
    ],
  },
  about: {
    title: "关于",
    meta: "Aearn 桌面端原型信息",
    cards: [
      ["版本", "V1 桌面端原型"],
      ["定位", "代码补全、运行预览、测试判定、复习变体闭环"],
      ["技术形态", "React + Vite + Tauri"],
      ["范围", "当前实现对齐 docs/design 原型结构"],
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

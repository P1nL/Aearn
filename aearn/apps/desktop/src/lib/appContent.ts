import type {
  AppRoute,
  NavGroupKey,
  SettingsKey,
  SettingsPanel,
} from "../appTypes";

export const ROUTE_META: Record<AppRoute, { crumb: string; hint: string }> = {
  onboarding: {
    crumb: "首次建档 / 学习路线生成",
    hint: "首次使用完成建档后进入学习页",
  },
  home: {
    crumb: "当前学习 / 对话练习",
    hint: "从学习路线选择知识点开始",
  },
  review: {
    crumb: "复习 / 到期知识点",
    hint: "复习完成后更新巩固安排",
  },
  notes: {
    crumb: "笔记 / 当前知识点",
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


export const NAV_DEFAULTS: Record<NavGroupKey, boolean> = {
  learn: true,
  review: true,
  notes: true,
  "notes-python": true,
  "notes-javascript": true,
  "notes-sql": false,
};

import type { LessonAuthoringRun, LessonDocument } from "../types";

export const lessonScope = {
  track_id: "22222222-2222-4222-8222-222222222222",
  module_key: "python-basics",
  module_diagnostic_allowed: false,
  knowledge_key: "n1_1_variables_and_types",
  track_version: 3,
  progress_version: 2,
  progress_status: "available",
};
export const lessonUserId = "11111111-1111-4111-8111-111111111111";
const citationId = "cite_1234567890abcdef";

export function lessonRun(state: LessonAuthoringRun["state"] = "pending"): LessonAuthoringRun {
  return {
    run_id: "33333333-3333-4333-8333-333333333333", state, run_kind: "prepare",
    attempt_count: state === "failed" ? 2 : 0,
    failure_code: state === "failed" ? "LESSON_DOCUMENT_INVALID" : null,
    failure_message: state === "failed" ? "课程生成结果未通过结构校验。" : null,
    created_at: "2026-09-04T00:00:00Z", updated_at: "2026-09-04T00:00:01Z",
    terminal_at: state === "failed" || state === "cancelled" ? "2026-09-04T00:00:01Z" : null,
  };
}

// Synthetic public payload: all ten registered block kinds, eleven ordered blocks.
// No live learner document or provider output is copied into this fixture.
export function readyLessonPayload() {
  const base = (block_id: string, order_index: number, cited = false) => ({ block_id, order_index, citation_ids: cited ? [citationId] : [] });
  const document: LessonDocument = {
    schema_version: "lesson_document_v1", title: "变量与基本数据类型", language_id: "python",
    knowledge_key: lessonScope.knowledge_key, content_standard_version: "lesson-content-v1",
    coverage_keys: [lessonScope.knowledge_key], content_hash: "a".repeat(64),
    blocks: [
      { ...base("heading", 0), type: "heading", title: "Python 变量", subtitle: "从赋值开始" },
      { ...base("objectives", 1), type: "learning_objectives", items: ["理解赋值"], coverage_keys: [lessonScope.knowledge_key] },
      { ...base("concept", 2, true), type: "concept", title: "变量与赋值", paragraphs: ["赋值将名称绑定到对象。"], coverage_keys: [lessonScope.knowledge_key] },
      { ...base("authority", 3, true), type: "authority_note", title: "官方说明", statement: "等号用于赋值。" },
      { ...base("example", 4, true), type: "code_example", title: "第一次赋值", language_id: "python", code: "count = 3", explanation: ["名称 count 绑定整数。"], execution_claim: "not_run" },
      { ...base("comparison", 5, true), type: "comparison", title: "值的类型", columns: ["值", "类型"], rows: [["3", "整数"]], conclusion: "值具有类型。" },
      { ...base("hint", 6), type: "hint", title: "观察提示", steps: ["先阅读赋值右侧。"] },
      { ...base("gate", 7), type: "exercise_gate", gate_key: "python-variable-check", gate_kind: "knowledge_check", assessment_contract_version: "gate-v1", required_capabilities: ["python.assignment"], learner_prompt: "解释赋值操作。" },
      { ...base("summary", 8, true), type: "summary", points: ["赋值绑定名称和值。"], coverage_keys: [lessonScope.knowledge_key] },
      { ...base("next", 9), type: "next_steps", items: ["继续阅读基本类型。"] },
      { ...base("types", 10, true), type: "concept", title: "基本类型", paragraphs: ["字符串表示文本。"], coverage_keys: [lessonScope.knowledge_key] },
    ],
  };
  return {
    ...lessonScope, status: "ready",
    assignment: {
      assignment_id: "44444444-4444-4444-8444-444444444444", document_id: "55555555-5555-4555-8555-555555555555",
      assignment_version: 1, status: "active", content_hash: document.content_hash,
      started_at: null, activated_at: "2026-09-04T00:00:02Z", progress_status: "available", progress_version: 2,
    },
    document,
    sources: [{
      citation_id: citationId, source_id: "python-tutorial", display_name: "Python 官方教程", provider: "Python",
      trust_tier: "official", source_type: "tutorial", source_version_label: "3.13", source_version_kind: "fixed",
      canonical_url: "https://docs.python.org/3.13/tutorial/introduction.html", section_path: ["Introduction"],
      fetched_at: "2026-09-04T00:00:00Z", snapshotted_at: "2026-09-04T00:00:02Z", evidence_excerpt: "The equal sign is used to assign a value to a variable.",
    }],
    update: null,
  };
}

export function lessonPreparePayload(status: "preparing" | "failed" | "ready", replayed = false) {
  return {
    status, track_id: lessonScope.track_id, knowledge_key: lessonScope.knowledge_key,
    authoring_run: status === "ready" ? null : lessonRun(status === "failed" ? "failed" : "pending"),
    idempotent_replayed: replayed,
  };
}

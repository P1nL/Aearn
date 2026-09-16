/** Shared strict public knowledge-check decoder; Gate and Review keep string submissions. */
type KnowledgeCheckOption = { optionId: string; label: string };
export type SupportedKnowledgePrompt = {
  promptMarkdown: string;
  responseKind: "single_select" | "short_text" | "prediction";
  options: KnowledgeCheckOption[];
};

export function supportedKnowledgePrompt(prompt: Record<string, unknown>, artifact: Record<string, unknown>): SupportedKnowledgePrompt | null {
  if (
    !hasExactKeys(prompt, ["schema_version", "prompt_markdown", "response_kind", "options"])
    || !hasExactKeys(artifact, ["schema_version", "response_kind", "options"])
    || prompt.schema_version !== "knowledge_check_prompt_v1"
    || artifact.schema_version !== "knowledge_check_artifact_v1"
    || typeof prompt.prompt_markdown !== "string"
    || !prompt.prompt_markdown.trim()
    || prompt.response_kind !== artifact.response_kind
  ) return null;
  const promptOptions = knowledgeCheckOptions(prompt.options);
  const artifactOptions = knowledgeCheckOptions(artifact.options);
  if (!promptOptions || !artifactOptions || !sameKnowledgeCheckOptions(promptOptions, artifactOptions)) return null;
  if (prompt.response_kind === "single_choice" || prompt.response_kind === "single_select") {
    return promptOptions.length >= 2 && promptOptions.length <= 12
      ? { promptMarkdown: prompt.prompt_markdown, responseKind: "single_select", options: promptOptions }
      : null;
  }
  if (prompt.response_kind === "short_text" || prompt.response_kind === "prediction") {
    return promptOptions.length === 0
      ? { promptMarkdown: prompt.prompt_markdown, responseKind: prompt.response_kind, options: [] }
      : null;
  }
  return null;
}
function knowledgeCheckOptions(value: unknown): KnowledgeCheckOption[] | null {
  if (!Array.isArray(value)) return null;
  const options: KnowledgeCheckOption[] = [];
  for (const item of value) {
    if (!isRecord(item) || !hasExactKeys(item, ["option_id", "label"]) || typeof item.option_id !== "string" || !item.option_id.trim() || typeof item.label !== "string" || !item.label.trim()) return null;
    options.push({ optionId: item.option_id, label: item.label });
  }
  return new Set(options.map((option) => option.optionId)).size === options.length ? options : null;
}
function sameKnowledgeCheckOptions(left: KnowledgeCheckOption[], right: KnowledgeCheckOption[]): boolean {
  return left.length === right.length && left.every((option, index) => option.optionId === right[index]?.optionId && option.label === right[index]?.label);
}
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function hasExactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

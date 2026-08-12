import type { ModelReviewFinding, ModelReviewFindingKind, ModelReviewSeverity } from "../../../types";

type ModelCodeReviewFindingEditorProps = {
  finding: ModelReviewFinding;
  index: number;
  lineCount: number;
  disabled: boolean;
  errors: string[];
  onChange: (finding: ModelReviewFinding) => void;
  onRemove: () => void;
};

export function ModelCodeReviewFindingEditor({
  finding,
  index,
  lineCount,
  disabled,
  errors,
  onChange,
  onRemove,
}: ModelCodeReviewFindingEditorProps) {
  const prefix = `model-review-finding-${finding.client_finding_id}`;
  const update = <Key extends keyof ModelReviewFinding>(key: Key, value: ModelReviewFinding[Key]) => {
    onChange({ ...finding, [key]: value });
  };
  const changeKind = (kind: ModelReviewFindingKind) => {
    onChange({
      ...finding,
      finding_kind: kind,
      severity: kind === "improvement" && !["info", "low"].includes(finding.severity) ? "low" : finding.severity,
    });
  };

  return (
    <fieldset className="model-review-finding" disabled={disabled}>
      <legend>发现 {index + 1}</legend>
      <button className="model-review-remove" type="button" onClick={onRemove} aria-label={`删除发现 ${index + 1}`}>删除</button>
      <div className="model-review-finding-grid">
        <label>
          <span>类型</span>
          <select value={finding.finding_kind} onChange={(event) => changeKind(event.target.value as ModelReviewFindingKind)}>
            <option value="correctness">正确性问题</option>
            <option value="improvement">改进建议</option>
          </select>
        </label>
        <label>
          <span>严重程度</span>
          <select value={finding.severity} onChange={(event) => update("severity", event.target.value as ModelReviewSeverity)}>
            <option value="info">提示</option>
            <option value="low">低</option>
            {finding.finding_kind === "correctness" ? <option value="medium">中</option> : null}
            {finding.finding_kind === "correctness" ? <option value="high">高</option> : null}
            {finding.finding_kind === "correctness" ? <option value="critical">严重</option> : null}
          </select>
        </label>
        <label>
          <span>起始行</span>
          <input type="number" min={1} max={lineCount} value={finding.start_line} onChange={(event) => update("start_line", Number(event.target.value))} />
        </label>
        <label>
          <span>结束行</span>
          <input type="number" min={1} max={lineCount} value={finding.end_line} onChange={(event) => update("end_line", Number(event.target.value))} />
        </label>
        <label className="model-review-wide">
          <span>分类键</span>
          <input id={`${prefix}-category`} value={finding.category} maxLength={120} placeholder="例如 edge_case" onChange={(event) => update("category", event.target.value)} />
        </label>
        <ReviewText label="触发条件" value={finding.trigger_condition} disabled={disabled} onChange={(value) => update("trigger_condition", value)} />
        <ReviewText label="违反原则" value={finding.principle} disabled={disabled} onChange={(value) => update("principle", value)} />
        <ReviewText label="可能影响" value={finding.impact} disabled={disabled} onChange={(value) => update("impact", value)} />
        <ReviewText label="验证方法" value={finding.validation_method} disabled={disabled} onChange={(value) => update("validation_method", value)} />
        <ReviewText label="建议修复" value={finding.suggested_fix} disabled={disabled} onChange={(value) => update("suggested_fix", value)} />
        <label className="model-review-wide">
          <span>补充说明（可选）</span>
          <textarea rows={2} maxLength={1200} value={finding.supplemental_note ?? ""} onChange={(event) => update("supplemental_note", event.target.value || null)} />
        </label>
      </div>
      {errors.length > 0 ? <ul className="model-review-field-errors" aria-live="polite">{errors.map((error) => <li key={error}>{error}</li>)}</ul> : null}
    </fieldset>
  );
}

function ReviewText({ label, value, disabled, onChange }: { label: string; value: string; disabled: boolean; onChange: (value: string) => void }) {
  return (
    <label className="model-review-wide">
      <span>{label}</span>
      <textarea rows={2} maxLength={1200} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

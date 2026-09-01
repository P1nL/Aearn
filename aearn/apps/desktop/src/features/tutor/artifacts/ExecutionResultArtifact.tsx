import { useEffect, useState } from "react";

import type {
  SafeExecutionLocation,
  SafeExecutionResultV2,
  SafeTableResultCell,
  TutorArtifactAttemptDetail,
  TutorArtifactOutcome,
  TutorArtifactSourceReference,
  TutorPublicArtifactItem,
} from "../../../types";
import { Button } from "../../../ui/dsh-derived";
import type { TutorArtifactAttemptLoader, TutorArtifactReturnToSource } from "./artifactRendererTypes";
import { loadArtifactAttemptCached } from "./artifactUiState";

export type ExecutionResultArtifactProps = {
  artifact: TutorPublicArtifactItem;
  loadAttempt?: TutorArtifactAttemptLoader;
  onReturnToSource?: TutorArtifactReturnToSource;
};

type AttemptDetailState =
  | { status: "pending" | "loading" | "unavailable" | "error"; detail: null }
  | { status: "ready"; detail: TutorArtifactAttemptDetail };

const OUTCOME_LABELS: Record<TutorArtifactOutcome, string> = {
  passed: "全部通过",
  failed: "仍有未通过项",
  timed_out: "运行超时",
  cancelled: "运行已取消",
  unavailable: "运行暂不可用",
  invalid: "结果无效",
};

const EXECUTION_STATUS_LABELS: Record<SafeExecutionResultV2["status"], string> = {
  success: "执行完成",
  compile_error: "编译失败",
  runtime_error: "运行错误",
  timeout: "执行超时",
  cancelled: "执行已取消",
  unsupported: "当前不支持执行",
  unavailable: "执行暂不可用",
  failed: "执行失败",
};

export function ExecutionResultArtifact({ artifact, loadAttempt, onReturnToSource }: ExecutionResultArtifactProps) {
  const presentation = artifact.presentation;
  if (presentation.type !== "test_result_v1") return <ArtifactResultContractError />;
  const [detailState, setDetailState] = useState<AttemptDetailState>(() => {
    if (presentation.status === "pending") return { status: "pending", detail: null };
    return loadAttempt ? { status: "loading", detail: null } : { status: "unavailable", detail: null };
  });

  useEffect(() => {
    if (presentation.status === "pending") {
      setDetailState({ status: "pending", detail: null });
      return;
    }
    if (!loadAttempt) {
      setDetailState({ status: "unavailable", detail: null });
      return;
    }
    let active = true;
    setDetailState({ status: "loading", detail: null });
    void loadArtifactAttemptCached(artifact, presentation.attempt_id, loadAttempt).then((detail) => {
      if (!attemptMatchesPresentation(detail, presentation)) {
        throw new Error("Tutor Artifact Attempt detail does not match the result presentation");
      }
      if (active) setDetailState({ status: "ready", detail });
    }).catch(() => {
      if (active) setDetailState({ status: "error", detail: null });
    });
    return () => { active = false; };
  }, [artifact, artifact.version, loadAttempt, presentation.attempt_id, presentation.status]);

  const detail = detailState.status === "ready" ? detailState.detail : null;
  const outcome = detail?.result?.outcome ?? presentation.outcome;
  const sourceReference = exactSourceArtifactReference(artifact.source_references);
  const executionResult = detail?.schema_version === "tutor_learning_artifact_attempt_v2"
    ? detail.result?.execution_result ?? null
    : null;
  const passedCount = executionResult?.passed_test_count ?? presentation.passed_count;
  const totalCount = executionResult?.total_test_count ?? presentation.total_count;

  return <section className="execution-result-artifact" aria-label="测试结果">
    <div className={`execution-result-overview${outcome ? ` outcome-${outcome}` : ""}`}>
      <div>
        <strong>{outcome ? OUTCOME_LABELS[outcome] : "结果生成中"}</strong>
        <span>{passedCount}/{totalCount} 项通过</span>
      </div>
      {executionResult ? <small>{EXECUTION_STATUS_LABELS[executionResult.status]} · {executionResult.duration_ms} ms</small> : null}
    </div>

    {detailState.status === "pending" ? <div className="execution-result-status" role="status">正在生成权威测试结果…</div> : null}
    {detailState.status === "loading" ? <div className="execution-result-status" role="status">正在加载权威测试明细…</div> : null}
    {detailState.status === "unavailable" ? <div className="execution-result-status">详细结果暂不可用。</div> : null}
    {detailState.status === "error" ? <ArtifactResultContractError /> : null}
    {detail?.schema_version === "tutor_learning_artifact_attempt_v1"
      ? <div className="execution-result-status">历史结果已读取；详细执行明细未记录。</div>
      : null}
    {detail?.schema_version === "tutor_learning_artifact_attempt_v2" && detail.result && !executionResult
      ? <div className="execution-result-status">此权威结果没有运行时明细。</div>
      : null}
    {executionResult ? <ExecutionResultDetail result={executionResult} /> : null}

    {outcome && outcome !== "passed" && sourceReference ? <div className="execution-result-return">
      <Button
        variant="outline"
        disabled={!onReturnToSource}
        onClick={() => onReturnToSource?.({ resultArtifact: artifact, sourceArtifactReference: sourceReference })}
      >返回修改</Button>
    </div> : null}
  </section>;
}

function ExecutionResultDetail({ result }: { result: SafeExecutionResultV2 }) {
  const failures = result.test_feedback.filter((item) => !item.passed);
  return <div className="execution-result-detail">
    {failures.length > 0 ? <ol className="execution-result-failures" aria-label="未通过项">
      {failures.map((failure) => <li key={failure.case_id}>
        <div className="execution-result-failure-heading">
          <strong>{failure.visible ? failure.case_id : "非公开测试"}</strong>
          <span>{failure.duration_ms} ms</span>
        </div>
        {failure.message ? <p>{failure.message}</p> : null}
        {failure.location ? <span className="execution-result-location">{formatLocation(failure.location)}</span> : null}
      </li>)}
    </ol> : null}
    {failures.length > 0 && result.passed_test_count > 0
      ? <p className="execution-result-passed-summary">其他 {result.passed_test_count} 项通过</p>
      : null}
    <ExecutionOutputDisclosures stdout={result.stdout} stderr={result.stderr} />
    {result.presentation.kind === "table_result_v1" ? <ExecutionResultTable
      columns={result.presentation.columns}
      rows={result.presentation.rows}
    /> : null}
  </div>;
}

function ExecutionOutputDisclosures({ stdout, stderr }: { stdout: string; stderr: string }) {
  if (!stdout && !stderr) return null;
  return <div className="execution-result-output-disclosures">
    {stdout ? <details><summary>标准输出</summary><pre>{stdout}</pre></details> : null}
    {stderr ? <details><summary>错误输出</summary><pre>{stderr}</pre></details> : null}
  </div>;
}

function ExecutionResultTable({ columns, rows }: { columns: string[]; rows: SafeTableResultCell[][] }) {
  return <div className="execution-result-table-scroll" tabIndex={0} aria-label="公开查询结果表格">
    <table>
      <thead><tr>{columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead>
      <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>
        {row.map((cell, cellIndex) => <td key={`${rowIndex}:${cellIndex}`}>{formatCell(cell)}</td>)}
      </tr>)}</tbody>
    </table>
  </div>;
}

function attemptMatchesPresentation(
  detail: TutorArtifactAttemptDetail,
  presentation: Extract<TutorPublicArtifactItem["presentation"], { type: "test_result_v1" }>,
): boolean {
  if (detail.attempt_id !== presentation.attempt_id || detail.status !== presentation.status) return false;
  if (detail.status !== "terminal" || !detail.result) return presentation.status === "pending";
  if (detail.result.outcome !== presentation.outcome || detail.result.result_hash !== presentation.result_hash) return false;
  if (detail.schema_version === "tutor_learning_artifact_attempt_v2" && detail.result.execution_result) {
    return detail.result.execution_result.passed_test_count === presentation.passed_count &&
      detail.result.execution_result.total_test_count === presentation.total_count;
  }
  return true;
}

function exactSourceArtifactReference(
  references: TutorArtifactSourceReference[],
): (TutorArtifactSourceReference & { kind: "artifact" }) | null {
  const matches = references.filter((reference): reference is TutorArtifactSourceReference & { kind: "artifact" } =>
    reference.kind === "artifact");
  return matches.length === 1 ? matches[0] : null;
}

function formatLocation(location: SafeExecutionLocation): string {
  const start = location.column === null ? `第 ${location.line} 行` : `第 ${location.line} 行，第 ${location.column} 列`;
  if (location.end_line === null) return start;
  const end = location.end_column === null
    ? `第 ${location.end_line} 行`
    : `第 ${location.end_line} 行，第 ${location.end_column} 列`;
  return `${start} 至 ${end}`;
}

function formatCell(value: SafeTableResultCell): string {
  if (value === null) return "NULL";
  return String(value);
}

function ArtifactResultContractError() {
  return <div className="inline-artifact-contract-error" role="alert"><strong>ARTIFACT_ATTEMPT_CONTRACT_ERROR</strong><span>权威测试结果暂不可用</span></div>;
}

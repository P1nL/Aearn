import type { SafeTableResultCell } from "../../../types";

export function SafeTableResultGrid({
  columns,
  rows,
  ariaLabel = "公开查询结果表格",
  className = "execution-result-table-scroll",
}: {
  columns: string[];
  rows: SafeTableResultCell[][];
  ariaLabel?: string;
  className?: string;
}) {
  return <div className={className} tabIndex={0} aria-label={ariaLabel}>
    <table>
      <thead><tr>{columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead>
      <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>
        {row.map((cell, cellIndex) => <td key={`${rowIndex}:${cellIndex}`}>{formatCell(cell)}</td>)}
      </tr>)}</tbody>
    </table>
  </div>;
}

function formatCell(value: SafeTableResultCell): string {
  if (value === null) return "NULL";
  return String(value);
}

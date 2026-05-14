import type { ApiHealthState } from "../appTypes";

export function ApiHealthChip({ apiHealth }: { apiHealth: ApiHealthState }) {
  if (apiHealth.status === "loading") {
    return <div className="status-chip">API 检测中</div>;
  }
  if (apiHealth.status === "offline") {
    return <div className="status-chip offline">API 离线 · {apiHealth.message}</div>;
  }
  return <div className="status-chip online">{apiHealth.data.service} 在线</div>;
}

import { useEffect, useState, type ReactNode } from "react";

import type { TutorPublicBranchGroup } from "../../../types";
import { readBranchExpanded, writeBranchExpanded } from "./artifactUiState";

export function ClarificationBranchGroup({ conversationId, branch, children }: {
  conversationId: string;
  branch: TutorPublicBranchGroup;
  children: ReactNode;
}) {
  const active = branch.state === "active";
  const [expanded, setExpanded] = useState(() => readBranchExpanded(conversationId, branch));
  const bodyId = `tutor-branch-${branch.branch_id}`;

  useEffect(() => {
    setExpanded(readBranchExpanded(conversationId, branch));
  }, [branch, conversationId]);

  function changeExpanded(next: boolean) {
    if (active) return;
    writeBranchExpanded(conversationId, branch, next);
    setExpanded(next);
  }

  return <section className={`tutor-clarification-branch ${branch.state}`} data-branch-id={branch.branch_id} data-anchor-artifact-id={branch.anchor_artifact_id}>
    <div className="tutor-branch-rail" aria-hidden="true" />
    {active
      ? <div className="tutor-branch-active-label" role="status">答疑进行中</div>
      : <button type="button" className="tutor-branch-summary" aria-expanded={expanded} aria-controls={bodyId} onClick={() => changeExpanded(!expanded)}>答疑 · {branch.round_count} 轮</button>}
    {(active || expanded) ? <div className="tutor-branch-items" id={bodyId}>{children}</div> : null}
  </section>;
}

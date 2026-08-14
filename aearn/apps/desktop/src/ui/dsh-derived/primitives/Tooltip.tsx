/* Reimplemented from the accessible label behavior and visual treatment of
 * upstream UI Tooltip.tsx at revision
 * 47f943859bef60e4160492346772ded9b24f765a (MIT). */
import { cloneElement, useId } from "react";
import type { ReactElement } from "react";
import { joinClassNames } from "../classNames";
import styles from "./Tooltip.module.css";

export type TooltipSide = "top" | "right" | "bottom" | "left";

interface TooltipAnchorProps {
  "aria-describedby"?: string;
}

export interface TooltipProps {
  label: string;
  children: ReactElement<TooltipAnchorProps>;
  side?: TooltipSide;
  disabledTarget?: boolean;
  className?: string;
}

export function Tooltip({ label, children, side = "top", disabledTarget = false, className }: TooltipProps) {
  const tooltipId = `aearn-tooltip-${useId().replace(/:/g, "")}`;
  const describedBy = [children.props["aria-describedby"], tooltipId].filter(Boolean).join(" ");
  const anchor = disabledTarget
    ? children
    : cloneElement(children, { "aria-describedby": describedBy });

  return (
    <span
      className={joinClassNames(styles.root, className)}
      data-side={side}
      aria-describedby={disabledTarget ? tooltipId : undefined}
      tabIndex={disabledTarget ? 0 : undefined}
      title={disabledTarget ? label : undefined}
    >
      {anchor}
      <span id={tooltipId} className={styles.bubble} role="tooltip">
        {label}
      </span>
    </span>
  );
}

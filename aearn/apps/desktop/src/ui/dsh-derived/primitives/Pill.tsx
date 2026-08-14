/* Adapted from upstream UI Pill.tsx at revision
 * 47f943859bef60e4160492346772ded9b24f765a (MIT). */
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { joinClassNames } from "../classNames";
import styles from "./Pill.module.css";

export interface PillProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  active?: boolean;
  children?: ReactNode;
}

export function Pill({ active = false, className, children, onClick, ...props }: PillProps) {
  const classes = joinClassNames(styles.pill, active && styles.active, className);
  if (!onClick) {
    return <span className={classes}>{children}</span>;
  }

  return (
    <button type="button" className={joinClassNames(classes, styles.interactive)} onClick={onClick} {...props}>
      {children}
    </button>
  );
}

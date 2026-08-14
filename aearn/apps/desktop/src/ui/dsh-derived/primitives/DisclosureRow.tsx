/* Reimplemented from the controlled interaction structure of upstream
 * UI DisclosureRow.tsx at revision 47f943859bef60e4160492346772ded9b24f765a (MIT). */
import { useId } from "react";
import type { ReactNode } from "react";
import { IconChevronDown } from "../icons";
import { joinClassNames } from "../classNames";
import styles from "./DisclosureRow.module.css";

export interface DisclosureRowProps {
  title: ReactNode;
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
  children: ReactNode;
  icon?: ReactNode;
  summary?: ReactNode;
  contentId?: string;
  disabled?: boolean;
  className?: string;
}

export function DisclosureRow({
  title,
  expanded,
  onExpandedChange,
  children,
  icon,
  summary,
  contentId,
  disabled = false,
  className,
}: DisclosureRowProps) {
  const generatedId = useId();
  const resolvedContentId = contentId ?? `aearn-disclosure-${generatedId.replace(/:/g, "")}`;

  return (
    <div className={joinClassNames(styles.root, className)} data-expanded={expanded || undefined}>
      <button
        type="button"
        className={styles.row}
        aria-expanded={expanded}
        aria-controls={resolvedContentId}
        disabled={disabled}
        onClick={() => onExpandedChange(!expanded)}
      >
        <span className={styles.leading} aria-hidden="true">
          {icon ?? <IconChevronDown className={styles.chevron} />}
        </span>
        <span className={styles.title}>{title}</span>
        {!expanded && summary ? <span className={styles.summary}>{summary}</span> : null}
        {icon ? <IconChevronDown className={styles.trailing} aria-hidden="true" /> : null}
      </button>
      <div id={resolvedContentId} className={styles.content} hidden={!expanded}>
        {children}
      </div>
    </div>
  );
}

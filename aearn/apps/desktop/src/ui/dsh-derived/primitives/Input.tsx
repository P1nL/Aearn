/* Adapted from upstream UI Input.tsx at revision
 * 47f943859bef60e4160492346772ded9b24f765a (MIT). */
import { forwardRef } from "react";
import type { InputHTMLAttributes, ReactNode } from "react";
import { joinClassNames } from "../classNames";
import styles from "./Input.module.css";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  icon?: ReactNode;
  invalid?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { icon, invalid = false, className, disabled, ...props },
  ref,
) {
  return (
    <span className={joinClassNames(styles.wrap, invalid && styles.invalid, disabled && styles.disabled, className)}>
      {icon ? <span className={styles.icon} aria-hidden="true">{icon}</span> : null}
      <input ref={ref} className={styles.input} disabled={disabled} aria-invalid={invalid || undefined} {...props} />
    </span>
  );
});

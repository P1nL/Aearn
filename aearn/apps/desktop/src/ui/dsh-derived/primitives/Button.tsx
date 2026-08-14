/* Adapted from upstream UI Button.tsx at revision
 * 47f943859bef60e4160492346772ded9b24f765a (MIT). */
import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { joinClassNames } from "../classNames";
import styles from "./Button.module.css";

export type ButtonVariant = "primary" | "outline" | "ghost" | "icon";
export type ButtonSize = "md" | "sm";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  busy?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "ghost",
    size = "md",
    icon,
    busy = false,
    disabled = false,
    className,
    children,
    type = "button",
    ...props
  },
  ref,
) {
  const unavailable = disabled || busy;

  return (
    <button
      ref={ref}
      type={type}
      className={joinClassNames(styles.button, styles[variant], styles[size], className)}
      disabled={unavailable}
      aria-busy={busy || undefined}
      {...props}
    >
      {busy ? <span className={styles.spinner} aria-hidden="true" /> : null}
      {!busy && icon ? <span className={styles.iconSlot} aria-hidden="true">{icon}</span> : null}
      {children ? <span className={styles.label}>{children}</span> : null}
    </button>
  );
});


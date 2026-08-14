/* Adapted from upstream UI markdown/MessageText.tsx at revision
 * 47f943859bef60e4160492346772ded9b24f765a (MIT). */
import type { HTMLAttributes } from "react";
import { joinClassNames } from "../classNames";
import styles from "./MessageText.module.css";

export interface MessageTextProps extends HTMLAttributes<HTMLDivElement> {
  text: string;
}

export function MessageText({ text, className, ...props }: MessageTextProps) {
  return <div className={joinClassNames(styles.text, className)} {...props}>{text}</div>;
}

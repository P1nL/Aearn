import type { HTMLAttributes, PropsWithChildren } from "react";
import { joinClassNames } from "./classNames";

export const DSH_DERIVED_ROOT_CLASS = "aearn-dsh-derived";

export type DshDerivedRootProps = PropsWithChildren<HTMLAttributes<HTMLDivElement>>;

export function DshDerivedRoot({ className, children, ...props }: DshDerivedRootProps) {
  return (
    <div className={joinClassNames(DSH_DERIVED_ROOT_CLASS, className)} {...props}>
      {children}
    </div>
  );
}

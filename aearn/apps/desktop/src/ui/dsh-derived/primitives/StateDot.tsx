/* Adapted from upstream UI StateDot.tsx at revision
 * 47f943859bef60e4160492346772ded9b24f765a (MIT). */
import { joinClassNames } from "../classNames";
import styles from "./StateDot.module.css";

export type StateDotState = "positive" | "warning" | "running" | "danger" | "idle";

const MATRIX_CELLS: ReadonlyArray<readonly [number, number]> = [
  [0, 0], [4, 0], [8, 0], [8, 4], [8, 8], [4, 8], [0, 8], [0, 4],
];

export interface StateDotProps {
  state: StateDotState;
  size?: number;
  className?: string;
}

export function StateDot({ state, size = 10, className }: StateDotProps) {
  if (state === "running") {
    return (
      <svg
        className={joinClassNames(styles.matrix, className)}
        data-state={state}
        width={size}
        height={size}
        viewBox="0 0 10 10"
        shapeRendering="crispEdges"
        aria-hidden="true"
      >
        {MATRIX_CELLS.map(([x, y], index) => (
          <rect
            key={`${x}-${y}`}
            className={styles.cell}
            x={x}
            y={y}
            width="2"
            height="2"
            style={{ animationDelay: `${(index - MATRIX_CELLS.length) * 125}ms` }}
          />
        ))}
      </svg>
    );
  }

  return (
    <span
      className={joinClassNames(styles.dot, className)}
      data-state={state}
      style={{ width: size, height: size }}
      aria-hidden="true"
    />
  );
}

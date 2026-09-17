import { afterEach, describe, expect, it } from "vitest";
import workspaceStyles from "../../../styles/60-learning-workspace.css?raw";

const mounted: HTMLElement[] = [];

function mountDock(hasShelf: boolean) {
  const style = document.createElement("style");
  style.textContent = workspaceStyles;
  const dock = document.createElement("div");
  dock.className = `tutor-composer-dock${hasShelf ? " has-action-shelf" : ""}`;
  const shelf = document.createElement("section");
  shelf.className = "composer-action-shelf";
  const button = document.createElement("button");
  button.textContent = "View exercise status";
  shelf.append(button);
  if (hasShelf) dock.append(shelf);
  document.head.append(style);
  document.body.append(dock);
  mounted.push(style, dock);
  return { dock, shelf, button };
}

afterEach(() => {
  for (const element of mounted.splice(0)) element.remove();
});

describe("Tutor composer action shelf layout", () => {
  it("reserves intrinsic shelf height rather than overlaying the Artifact timeline", () => {
    const { dock, shelf, button } = mountDock(true);
    expect(getComputedStyle(dock).display).toBe("flex");
    expect(getComputedStyle(dock).flexDirection).toBe("column");
    expect(getComputedStyle(shelf).position).toBe("relative");
    expect(getComputedStyle(shelf).transform).not.toMatch(/translate|matrix/);
    expect(getComputedStyle(shelf).flexShrink).toBe("0");
    expect(getComputedStyle(button).pointerEvents).toBe("auto");
  });

  it("preserves the shelf-free composer layout", () => {
    const { dock } = mountDock(false);
    expect(getComputedStyle(dock).display).toBe("contents");
  });
});

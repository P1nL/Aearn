import { readFileSync, readdirSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import aearnTokens from "../tokens/aearn-light.css?raw";
import compatTokens from "../tokens/dsh-compat.css?raw";

const testsDirectory = dirname(fileURLToPath(import.meta.url));
const foundationDirectory = join(testsDirectory, "..");

function productionFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "tests" ? [] : productionFiles(path);
    }
    return [".ts", ".tsx", ".css"].includes(extname(entry.name)) ? [path] : [];
  });
}

describe("DSH-derived foundation boundaries", () => {
  it("publishes only Aearn semantic tokens", () => {
    expect(aearnTokens).toContain("--aearn-canvas: #ffffff");
    expect(aearnTokens).toContain("--aearn-brand: #14804a");
    expect(aearnTokens).toContain("prefers-reduced-motion");
    expect(aearnTokens).not.toContain("--dsw-");
  });

  it("keeps upstream compatibility aliases scoped to the derived root", () => {
    expect(compatTokens.trimStart().startsWith("/*")).toBe(true);
    expect(compatTokens).toContain(".aearn-dsh-derived {");
    expect(compatTokens).toContain("--dsw-alias-brand-primary: var(--aearn-brand)");
    expect(compatTokens).not.toContain(":root");
    expect(compatTokens).not.toContain("data-ds-dark-theme");
  });

  it("keeps focus, narrow-container, and reduced-motion guardrails in CSS", () => {
    const buttonCss = readFileSync(join(foundationDirectory, "primitives", "Button.module.css"), "utf8");
    const inputCss = readFileSync(join(foundationDirectory, "primitives", "Input.module.css"), "utf8");
    const disclosureCss = readFileSync(join(foundationDirectory, "primitives", "DisclosureRow.module.css"), "utf8");
    const tooltipCss = readFileSync(join(foundationDirectory, "primitives", "Tooltip.module.css"), "utf8");
    const stateDotCss = readFileSync(join(foundationDirectory, "primitives", "StateDot.module.css"), "utf8");

    expect(buttonCss).toContain(":focus-visible");
    expect(inputCss).toContain(":focus-within");
    expect(disclosureCss).toContain("min-width: 0");
    expect(disclosureCss).toContain(":focus-visible");
    expect(tooltipCss).toContain(":focus-visible");
    expect(buttonCss + disclosureCss + tooltipCss + stateDotCss).toContain("prefers-reduced-motion: reduce");
  });

  it("does not add an upstream runtime dependency to the desktop package", () => {
    const packageJson = readFileSync(join(foundationDirectory, "..", "..", "..", "package.json"), "utf8");
    expect(packageJson).not.toMatch(/@deepseek-ai|cordis/i);
    expect(packageJson).toContain('"sonner"');
  });

  it("has no product runtime, store, API, or brand dependency", () => {
    for (const file of productionFiles(foundationDirectory)) {
      const content = readFileSync(file, "utf8");
      const name = relative(foundationDirectory, file).replace(/\\/g, "/");
      expect(content, name).not.toMatch(/@deepseek-ai|cordis|features\/tutor|stores\/|(?:^|\/)api(?:\.ts)?["']/i);
      expect(content, name).not.toMatch(/FishLogo|BrandWordmark|DeepSeek/);
      if (name !== "tokens/dsh-compat.css") {
        expect(content, name).not.toContain("--dsw-");
      }
    }
  });
});

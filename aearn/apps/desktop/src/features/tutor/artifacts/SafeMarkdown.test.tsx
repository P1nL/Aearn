import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SafeMarkdown, isReadableDirectiveColor, isSafeMarkdownUrl } from "./SafeMarkdown";

describe("SafeMarkdown", () => {
  beforeEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("renders the approved AST features while keeping raw HTML, script, and style inert", () => {
    const { container } = render(<SafeMarkdown markdown={`# 标题

> 引用 **重点**

- 第一项
- 第二项

普通 *强调* 和 \`inline\`。

<script>window.hacked = true</script>
<style>body{display:none}</style>
<div onclick="alert(1)">raw html</div>`} />);

    expect(screen.getByRole("heading", { name: "标题" })).toBeInTheDocument();
    expect(screen.getByText("重点").tagName).toBe("STRONG");
    expect(screen.getByText("强调").tagName).toBe("EM");
    expect(screen.getByText("inline").tagName).toBe("CODE");
    expect(screen.getByRole("list")).toHaveTextContent("第一项第二项");
    expect(container.querySelector("blockquote")).toHaveTextContent("引用 重点");
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("style")).toBeNull();
    expect(container.querySelector("div[onclick]")).toBeNull();
    expect(container).toHaveTextContent("<script>window.hacked = true</script>");
    expect(container).toHaveTextContent("<style>body{display:none}</style>");
  });

  it("allows exact size and readable color directives and recovers invalid directive text unstyled", () => {
    const { container } = render(<SafeMarkdown surface="artifact" markdown={`:size[小字]{value="sm"} :size[大字]{value="xl"}

:color[可读颜色]{value="#005A3C"}

:color[低对比]{value="#777777"}

:size[错误字号]{value="xxl"}

:color[不完整颜色]

:size[不完整字号`} />);

    expect(screen.getByText("小字")).toHaveClass("safe-markdown-size-sm");
    expect(screen.getByText("大字")).toHaveClass("safe-markdown-size-xl");
    expect(screen.getByText("可读颜色")).toHaveStyle({ color: "rgb(0, 90, 60)" });
    for (const text of ["低对比", "错误字号", "不完整颜色", "不完整字号"]) {
      const node = screen.getByText(text);
      expect(node).not.toHaveClass("safe-markdown-color", "safe-markdown-size-sm", "safe-markdown-size-xl");
      expect(node).not.toHaveAttribute("style");
    }
    expect(container).not.toHaveTextContent(":color[");
    expect(container).not.toHaveTextContent(":size[");
    expect(isReadableDirectiveColor("#005A3C", "artifact")).toBe(true);
    expect(isReadableDirectiveColor("#777777", "artifact")).toBe(false);
    expect(isReadableDirectiveColor("red", "artifact")).toBe(false);
  });

  it("allows public credential-free http/https URLs and fragments while blocking app navigation and local hosts", () => {
    render(<SafeMarkdown markdown={`[HTTPS](https://example.com/docs)
[HTTP](http://example.com)
[relative](../lesson/1)
[fragment](#section-1)
[javascript](javascript:alert(1))
[credentials](https://user:pass@example.com/secret)
[protocol relative](//example.com/path)
[localhost](http://localhost:1420/private)
[loopback](http://127.0.0.1/private)
[data](data:text/html,boom)`} />);

    expect(screen.getByRole("link", { name: "HTTPS" })).toHaveAttribute("href", "https://example.com/docs");
    expect(screen.getByRole("link", { name: "HTTPS" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByRole("link", { name: "HTTP" })).toHaveAttribute("href", "http://example.com");
    expect(screen.getByRole("link", { name: "fragment" })).toHaveAttribute("href", "#section-1");
    for (const label of ["relative", "javascript", "credentials", "protocol relative", "localhost", "loopback", "data"]) {
      expect(screen.queryByRole("link", { name: label })).not.toBeInTheDocument();
      expect(document.body).toHaveTextContent(label);
    }
    expect(isSafeMarkdownUrl("../lesson/1")).toBe(false);
    expect(isSafeMarkdownUrl("//example.com/path")).toBe(false);
    expect(isSafeMarkdownUrl("https://user:pass@example.com")).toBe(false);
    expect(isSafeMarkdownUrl("http://localhost:1420/private")).toBe(false);
    expect(isSafeMarkdownUrl("http://127.0.0.1/private")).toBe(false);
    expect(isSafeMarkdownUrl("javascript:alert(1)")).toBe(false);
  });

  it("keeps an unmatched fenced block as the same injection-safe code node until closure", () => {
    const { container, rerender } = render(<SafeMarkdown streaming markdown={'```html\n<script>alert(1)</script>\n<div>partial'} />);
    const initialFigure = container.querySelector(".safe-markdown-code");
    expect(initialFigure).toHaveAttribute("data-complete", "false");
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector(".safe-markdown-code code")?.textContent).toBe("<script>alert(1)</script>\n<div>partial");

    rerender(<SafeMarkdown streaming markdown={'```html\n<script>alert(1)</script>\n<div>partial\n```'} />);
    const completedFigure = container.querySelector(".safe-markdown-code");
    expect(completedFigure).toBe(initialFigure);
    expect(completedFigure).toHaveAttribute("data-complete", "true");
    expect(container.querySelector("script")).toBeNull();
  });

  it("renders a bounded table and copies fenced code through the explicit control", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
    render(<SafeMarkdown markdown={`| 名称 | 值 |
| --- | --- |
| alpha | 1 |
| beta | **2** |

\`\`\`ts
const total = 2;
\`\`\``} />);

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "名称" })).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("2").tagName).toBe("STRONG");
    expect(screen.getByText("const")).toHaveClass("safe-markdown-token-keyword");
    await user.click(screen.getByRole("button", { name: "复制代码" }));
    expect(writeText).toHaveBeenCalledWith("const total = 2;");
    expect(screen.getByRole("button", { name: "复制代码" })).toHaveTextContent("已复制");
  });
});

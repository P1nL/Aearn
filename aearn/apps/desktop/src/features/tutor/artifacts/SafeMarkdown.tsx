import { useState, type ReactNode } from "react";

export type SafeMarkdownSurface = "message" | "artifact";

type MarkdownInlineNode =
  | { type: "text"; value: string }
  | { type: "break" }
  | { type: "emphasis"; children: MarkdownInlineNode[] }
  | { type: "strong"; children: MarkdownInlineNode[] }
  | { type: "inline_code"; value: string }
  | { type: "link"; href: string; children: MarkdownInlineNode[] }
  | { type: "size"; value: "sm" | "md" | "lg" | "xl"; children: MarkdownInlineNode[] }
  | { type: "color"; value: string; children: MarkdownInlineNode[] };

export type SafeMarkdownAstNode =
  | { type: "heading"; level: 1 | 2 | 3 | 4 | 5 | 6; children: MarkdownInlineNode[] }
  | { type: "paragraph"; children: MarkdownInlineNode[] }
  | { type: "blockquote"; children: SafeMarkdownAstNode[] }
  | { type: "list"; ordered: boolean; items: MarkdownInlineNode[][] }
  | { type: "code"; language: string | null; value: string; complete: boolean }
  | { type: "table"; header: MarkdownInlineNode[][]; rows: MarkdownInlineNode[][][] };

export type SafeMarkdownProps = {
  markdown: string;
  surface?: SafeMarkdownSurface;
  className?: string;
  streaming?: boolean;
};

const SURFACE_BACKGROUNDS: Record<SafeMarkdownSurface, string> = {
  message: "#FFFFFF",
  artifact: "#F6FAF8",
};
const DIRECTIVE_STARTS = [":size[", ":color["] as const;
const COLOR_PATTERN = /^#[0-9A-Fa-f]{6}$/;
type CodeTokenKind = "plain" | "comment" | "string" | "number" | "keyword" | "tag";
type CodeToken = { kind: CodeTokenKind; value: string };

const CODE_KEYWORDS: Record<string, ReadonlySet<string>> = {
  javascript: new Set(["as", "async", "await", "break", "case", "catch", "class", "const", "continue", "default", "delete", "do", "else", "export", "extends", "false", "finally", "for", "from", "function", "if", "import", "in", "instanceof", "let", "new", "null", "of", "return", "static", "super", "switch", "this", "throw", "true", "try", "typeof", "undefined", "var", "void", "while", "yield"]),
  python: new Set(["and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del", "elif", "else", "except", "False", "finally", "for", "from", "global", "if", "import", "in", "is", "lambda", "None", "nonlocal", "not", "or", "pass", "raise", "return", "True", "try", "while", "with", "yield"]),
  sql: new Set(["all", "and", "as", "asc", "by", "case", "create", "delete", "desc", "distinct", "drop", "else", "end", "from", "group", "having", "in", "insert", "into", "is", "join", "limit", "not", "null", "on", "or", "order", "select", "set", "table", "then", "union", "update", "values", "when", "where"]),
  json: new Set(["false", "null", "true"]),
  shell: new Set(["case", "do", "done", "elif", "else", "esac", "export", "fi", "for", "function", "if", "in", "then", "while"]),
};

export function SafeMarkdown({ markdown, surface = "message", className, streaming = false }: SafeMarkdownProps) {
  const ast = parseSafeMarkdown(markdown, surface);
  return <div className={`safe-markdown safe-markdown-${surface}${streaming ? " is-streaming" : ""}${className ? ` ${className}` : ""}`} data-streaming={streaming || undefined}>
    {ast.map((node, index) => <MarkdownBlock key={`${node.type}:${index}`} node={node} surface={surface} streaming={streaming} />)}
  </div>;
}

export function parseSafeMarkdown(markdown: string, surface: SafeMarkdownSurface = "message"): SafeMarkdownAstNode[] {
  return parseBlocks(markdown.replace(/\r\n?/g, "\n").split("\n"), surface);
}

export function isSafeMarkdownUrl(value: string): boolean {
  const href = value.trim();
  if (!href || /[\u0000-\u001F\u007F]/.test(href) || href.includes("\\")) return false;
  if (href.startsWith("#")) return /^#[A-Za-z0-9._:-]+$/.test(href);
  if (!/^https?:\/\//i.test(href)) return false;
  try {
    const parsed = new URL(href);
    if (parsed.username || parsed.password || (parsed.protocol !== "http:" && parsed.protocol !== "https:")) return false;
    return isAllowedMarkdownHostname(parsed.hostname);
  } catch {
    return false;
  }
}

function isAllowedMarkdownHostname(value: string): boolean {
  const hostname = value.replace(/^\[|\]$/g, "").toLowerCase();
  if (!hostname || hostname === "localhost" || hostname.endsWith(".localhost") || hostname.endsWith(".local")) return false;
  if (hostname.includes(":") || /^\d+(?:\.\d+){3}$/.test(hostname)) return false;
  return hostname.includes(".");
}

export function isReadableDirectiveColor(color: string, surface: SafeMarkdownSurface): boolean {
  if (!COLOR_PATTERN.test(color)) return false;
  return contrastRatio(color, SURFACE_BACKGROUNDS[surface]) >= 4.5;
}

function parseBlocks(lines: string[], surface: SafeMarkdownSurface): SafeMarkdownAstNode[] {
  const nodes: SafeMarkdownAstNode[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index] ?? "";
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^\s{0,3}(```+|~~~+)\s*([A-Za-z0-9_+.-]*)\s*$/);
    if (fence) {
      const marker = fence[1];
      const language = fence[2] || null;
      const content: string[] = [];
      let complete = false;
      index += 1;
      while (index < lines.length) {
        const candidate = lines[index] ?? "";
        const closing = candidate.match(/^\s{0,3}(```+|~~~+)\s*$/);
        if (closing && closing[1][0] === marker[0] && closing[1].length >= marker.length) {
          complete = true;
          index += 1;
          break;
        }
        content.push(candidate);
        index += 1;
      }
      nodes.push({ type: "code", language, value: content.join("\n"), complete });
      continue;
    }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+)$/);
    if (heading) {
      nodes.push({
        type: "heading",
        level: heading[1].length as 1 | 2 | 3 | 4 | 5 | 6,
        children: parseInline(heading[2], surface),
      });
      index += 1;
      continue;
    }

    if (/^\s{0,3}>/.test(line)) {
      const quoted: string[] = [];
      while (index < lines.length && /^\s{0,3}>/.test(lines[index] ?? "")) {
        quoted.push((lines[index] ?? "").replace(/^\s{0,3}>\s?/, ""));
        index += 1;
      }
      nodes.push({ type: "blockquote", children: parseBlocks(quoted, surface) });
      continue;
    }

    const listMatch = line.match(/^\s{0,3}(?:(\d+)[.)]|([-+*]))\s+(.+)$/);
    if (listMatch) {
      const ordered = Boolean(listMatch[1]);
      const items: MarkdownInlineNode[][] = [];
      while (index < lines.length) {
        const item = (lines[index] ?? "").match(/^\s{0,3}(?:(\d+)[.)]|([-+*]))\s+(.+)$/);
        if (!item || Boolean(item[1]) !== ordered) break;
        items.push(parseInline(item[3], surface));
        index += 1;
      }
      nodes.push({ type: "list", ordered, items });
      continue;
    }

    if (index + 1 < lines.length && isTableSeparator(lines[index + 1] ?? "")) {
      const headerCells = splitTableRow(line);
      const separatorCells = splitTableRow(lines[index + 1] ?? "");
      if (headerCells.length > 0 && headerCells.length === separatorCells.length) {
        index += 2;
        const rows: MarkdownInlineNode[][][] = [];
        while (index < lines.length && (lines[index] ?? "").includes("|") && (lines[index] ?? "").trim()) {
          const cells = splitTableRow(lines[index] ?? "");
          rows.push(headerCells.map((_, cellIndex) => parseInline(cells[cellIndex] ?? "", surface)));
          index += 1;
        }
        nodes.push({
          type: "table",
          header: headerCells.map((cell) => parseInline(cell, surface)),
          rows,
        });
        continue;
      }
    }

    const paragraph: string[] = [line];
    index += 1;
    while (index < lines.length && (lines[index] ?? "").trim() && !startsBlock(lines, index)) {
      paragraph.push(lines[index] ?? "");
      index += 1;
    }
    nodes.push({ type: "paragraph", children: parseInline(paragraph.join("\n"), surface) });
  }
  return nodes;
}

function startsBlock(lines: string[], index: number): boolean {
  const line = lines[index] ?? "";
  return /^\s{0,3}(```+|~~~+)/.test(line)
    || /^\s{0,3}#{1,6}\s+/.test(line)
    || /^\s{0,3}>/.test(line)
    || /^\s{0,3}(?:(?:\d+)[.)]|[-+*])\s+/.test(line)
    || (index + 1 < lines.length && isTableSeparator(lines[index + 1] ?? ""));
}

function isTableSeparator(line: string): boolean {
  const cells = splitTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
}

function splitTableRow(line: string): string[] {
  let value = line.trim();
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|")) value = value.slice(0, -1);
  const cells: string[] = [];
  let current = "";
  let escaped = false;
  for (const char of value) {
    if (escaped) {
      current += char;
      escaped = false;
    } else if (char === "\\") {
      escaped = true;
    } else if (char === "|") {
      cells.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  cells.push(current.trim());
  return cells;
}

function parseInline(value: string, surface: SafeMarkdownSurface): MarkdownInlineNode[] {
  const nodes: MarkdownInlineNode[] = [];
  const pushText = (text: string) => {
    if (!text) return;
    const previous = nodes[nodes.length - 1];
    if (previous?.type === "text") previous.value += text;
    else nodes.push({ type: "text", value: text });
  };
  let index = 0;
  while (index < value.length) {
    if (value[index] === "\n") {
      nodes.push({ type: "break" });
      index += 1;
      continue;
    }
    if (value[index] === "\\" && index + 1 < value.length) {
      pushText(value[index + 1]);
      index += 2;
      continue;
    }

    const remaining = value.slice(index);
    const directiveStart = DIRECTIVE_STARTS.find((prefix) => remaining.startsWith(prefix));
    if (directiveStart) {
      const size = remaining.match(/^:size\[([^\]\n]*)\]\{value="(sm|md|lg|xl)"\}/);
      if (size) {
        nodes.push({ type: "size", value: size[2] as "sm" | "md" | "lg" | "xl", children: parseInline(size[1], surface) });
        index += size[0].length;
        continue;
      }
      const color = remaining.match(/^:color\[([^\]\n]*)\]\{value="(#[0-9A-Fa-f]{6})"\}/);
      if (color && isReadableDirectiveColor(color[2], surface)) {
        nodes.push({ type: "color", value: color[2].toUpperCase(), children: parseInline(color[1], surface) });
        index += color[0].length;
        continue;
      }
      const recovered = recoverDirectiveText(remaining, directiveStart);
      pushText(recovered.text);
      index += recovered.length;
      continue;
    }

    if (remaining.startsWith("`")) {
      const closing = value.indexOf("`", index + 1);
      if (closing > index + 1) {
        nodes.push({ type: "inline_code", value: value.slice(index + 1, closing) });
        index = closing + 1;
        continue;
      }
    }

    const strongMarker = remaining.startsWith("**") ? "**" : remaining.startsWith("__") ? "__" : null;
    if (strongMarker) {
      const closing = value.indexOf(strongMarker, index + 2);
      if (closing > index + 2) {
        nodes.push({ type: "strong", children: parseInline(value.slice(index + 2, closing), surface) });
        index = closing + 2;
        continue;
      }
    }

    if (remaining.startsWith("[") && !remaining.startsWith("![")) {
      const labelEnd = value.indexOf("](", index + 1);
      if (labelEnd > index + 1) {
        const hrefEnd = findLinkDestinationEnd(value, labelEnd + 2);
        if (hrefEnd > labelEnd + 2) {
          const label = value.slice(index + 1, labelEnd);
          const href = value.slice(labelEnd + 2, hrefEnd).trim();
          if (isSafeMarkdownUrl(href)) nodes.push({ type: "link", href, children: parseInline(label, surface) });
          else pushText(label);
          index = hrefEnd + 1;
          continue;
        }
      }
    }

    const emphasisMarker = remaining.startsWith("*") ? "*" : remaining.startsWith("_") ? "_" : null;
    if (emphasisMarker) {
      const closing = value.indexOf(emphasisMarker, index + 1);
      if (closing > index + 1) {
        nodes.push({ type: "emphasis", children: parseInline(value.slice(index + 1, closing), surface) });
        index = closing + 1;
        continue;
      }
    }

    pushText(value[index] ?? "");
    index += 1;
  }
  return nodes;
}

function findLinkDestinationEnd(value: string, start: number): number {
  let nested = 0;
  for (let index = start; index < value.length; index += 1) {
    if (value[index] === "(") nested += 1;
    else if (value[index] === ")") {
      if (nested === 0) return index;
      nested -= 1;
    }
  }
  return -1;
}

function recoverDirectiveText(remaining: string, prefix: typeof DIRECTIVE_STARTS[number]): { text: string; length: number } {
  const bodyStart = prefix.length;
  const closingBracket = remaining.indexOf("]", bodyStart);
  const closingBrace = remaining.indexOf("}", Math.max(bodyStart, closingBracket));
  const length = closingBrace >= 0 ? closingBrace + 1 : remaining.length;
  if (closingBracket >= bodyStart) return { text: remaining.slice(bodyStart, closingBracket), length };
  const configurationStart = remaining.indexOf("{", bodyStart);
  const textEnd = configurationStart >= 0 ? configurationStart : remaining.length;
  return { text: remaining.slice(bodyStart, textEnd), length };
}

function MarkdownBlock({ node, surface, streaming }: { node: SafeMarkdownAstNode; surface: SafeMarkdownSurface; streaming: boolean }) {
  if (node.type === "heading") {
    const content = renderInline(node.children, `${node.type}-${node.level}`);
    if (node.level === 1) return <h1>{content}</h1>;
    if (node.level === 2) return <h2>{content}</h2>;
    if (node.level === 3) return <h3>{content}</h3>;
    if (node.level === 4) return <h4>{content}</h4>;
    if (node.level === 5) return <h5>{content}</h5>;
    return <h6>{content}</h6>;
  }
  if (node.type === "paragraph") return <p className={streaming ? "is-streaming" : undefined}>{renderInline(node.children, "paragraph")}</p>;
  if (node.type === "blockquote") return <blockquote>{node.children.map((child, index) => <MarkdownBlock key={`${child.type}:${index}`} node={child} surface={surface} streaming={streaming} />)}</blockquote>;
  if (node.type === "list") {
    const Tag = node.ordered ? "ol" : "ul";
    return <Tag>{node.items.map((item, index) => <li key={index}>{renderInline(item, `list-${index}`)}</li>)}</Tag>;
  }
  if (node.type === "table") return <div className="safe-markdown-table-scroll" tabIndex={0} aria-label="Markdown 表格，可横向滚动"><table><thead><tr>{node.header.map((cell, index) => <th key={index} scope="col">{renderInline(cell, `header-${index}`)}</th>)}</tr></thead><tbody>{node.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{renderInline(cell, `row-${rowIndex}-${cellIndex}`)}</td>)}</tr>)}</tbody></table></div>;
  return <CodeBlock language={node.language} value={node.value} complete={node.complete} />;
}

function CodeBlock({ language, value, complete }: { language: string | null; value: string; complete: boolean }) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  async function copyCode() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(value);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  }
  const label = copyState === "copied" ? "已复制" : copyState === "failed" ? "复制失败" : "复制代码";
  return <figure className="safe-markdown-code" data-complete={complete}>
    <figcaption><span>{language ?? "code"}</span><button type="button" onClick={() => void copyCode()} aria-label="复制代码">{label}</button></figcaption>
    <pre><code className={language ? `language-${language}` : undefined}>{renderHighlightedCode(value, language)}</code></pre>
  </figure>;
}

function renderHighlightedCode(value: string, language: string | null): ReactNode {
  const syntax = normalizedCodeSyntax(language);
  if (!syntax) return value;
  const tokens = syntax === "markup" ? tokenizeMarkup(value) : tokenizeCode(value, syntax);
  return tokens.map((token, index) => token.kind === "plain"
    ? token.value
    : <span key={`${token.kind}:${index}`} className={`safe-markdown-token-${token.kind}`}>{token.value}</span>);
}

function normalizedCodeSyntax(language: string | null): "javascript" | "python" | "sql" | "json" | "shell" | "css" | "markup" | null {
  const value = language?.toLowerCase() ?? "";
  if (["js", "jsx", "mjs", "cjs", "ts", "tsx", "typescript", "javascript"].includes(value)) return "javascript";
  if (["py", "python"].includes(value)) return "python";
  if (["sql", "sqlite"].includes(value)) return "sql";
  if (value === "json") return "json";
  if (["bash", "sh", "shell", "powershell", "ps1"].includes(value)) return "shell";
  if (value === "css") return "css";
  if (["html", "xml", "svg", "markup"].includes(value)) return "markup";
  return null;
}

function tokenizeMarkup(value: string): CodeToken[] {
  const tokens: CodeToken[] = [];
  const pattern = /<!--[\s\S]*?-->|<\/?[A-Za-z][^>]*>/g;
  let offset = 0;
  for (const match of value.matchAll(pattern)) {
    const index = match.index ?? 0;
    pushCodeToken(tokens, "plain", value.slice(offset, index));
    pushCodeToken(tokens, match[0].startsWith("<!--") ? "comment" : "tag", match[0]);
    offset = index + match[0].length;
  }
  pushCodeToken(tokens, "plain", value.slice(offset));
  return tokens;
}

function tokenizeCode(value: string, syntax: "javascript" | "python" | "sql" | "json" | "shell" | "css"): CodeToken[] {
  const tokens: CodeToken[] = [];
  const keywords = CODE_KEYWORDS[syntax] ?? new Set<string>();
  const caseInsensitiveKeywords = syntax === "sql";
  let index = 0;
  while (index < value.length) {
    const remaining = value.slice(index);
    const lineComment = (syntax === "python" || syntax === "shell") && remaining.startsWith("#")
      || syntax === "sql" && remaining.startsWith("--")
      || (syntax === "javascript" || syntax === "json") && remaining.startsWith("//");
    if (lineComment) {
      const end = value.indexOf("\n", index);
      const stop = end < 0 ? value.length : end;
      pushCodeToken(tokens, "comment", value.slice(index, stop));
      index = stop;
      continue;
    }
    if ((syntax === "javascript" || syntax === "sql" || syntax === "css" || syntax === "json") && remaining.startsWith("/*")) {
      const end = value.indexOf("*/", index + 2);
      const stop = end < 0 ? value.length : end + 2;
      pushCodeToken(tokens, "comment", value.slice(index, stop));
      index = stop;
      continue;
    }
    const quote = value[index];
    if (quote === "\"" || quote === "'" || (quote === "`" && syntax === "javascript")) {
      let stop = index + 1;
      while (stop < value.length) {
        if (value[stop] === "\\") { stop += 2; continue; }
        if (value[stop] === quote) { stop += 1; break; }
        stop += 1;
      }
      pushCodeToken(tokens, "string", value.slice(index, stop));
      index = stop;
      continue;
    }
    const number = remaining.match(/^(?:0x[0-9a-f]+|\d+(?:\.\d+)?(?:e[+-]?\d+)?)/i);
    if (number) {
      pushCodeToken(tokens, "number", number[0]);
      index += number[0].length;
      continue;
    }
    const identifier = remaining.match(/^[A-Za-z_$][A-Za-z0-9_$]*/);
    if (identifier) {
      const lookup = caseInsensitiveKeywords ? identifier[0].toLowerCase() : identifier[0];
      pushCodeToken(tokens, keywords.has(lookup) ? "keyword" : "plain", identifier[0]);
      index += identifier[0].length;
      continue;
    }
    pushCodeToken(tokens, "plain", value[index] ?? "");
    index += 1;
  }
  return tokens;
}

function pushCodeToken(tokens: CodeToken[], kind: CodeTokenKind, value: string): void {
  if (!value) return;
  const previous = tokens[tokens.length - 1];
  if (previous?.kind === kind) previous.value += value;
  else tokens.push({ kind, value });
}

function renderInline(nodes: MarkdownInlineNode[], keyPrefix: string): ReactNode[] {
  return nodes.map((node, index) => {
    const key = `${keyPrefix}:${node.type}:${index}`;
    if (node.type === "text") return node.value;
    if (node.type === "break") return <br key={key} />;
    if (node.type === "inline_code") return <code key={key}>{node.value}</code>;
    if (node.type === "emphasis") return <em key={key}>{renderInline(node.children, key)}</em>;
    if (node.type === "strong") return <strong key={key}>{renderInline(node.children, key)}</strong>;
    if (node.type === "size") return <span key={key} className={`safe-markdown-size-${node.value}`}>{renderInline(node.children, key)}</span>;
    if (node.type === "color") return <span key={key} className="safe-markdown-color" style={{ color: node.value }}>{renderInline(node.children, key)}</span>;
    const absolute = /^[A-Za-z][A-Za-z0-9+.-]*:/.test(node.href) || node.href.startsWith("//");
    return <a key={key} href={node.href} target={absolute ? "_blank" : undefined} rel={absolute ? "noopener noreferrer" : undefined}>{renderInline(node.children, key)}</a>;
  });
}

function contrastRatio(foreground: string, background: string): number {
  const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

function relativeLuminance(color: string): number {
  const channels = [color.slice(1, 3), color.slice(3, 5), color.slice(5, 7)].map((channel) => {
    const value = Number.parseInt(channel, 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

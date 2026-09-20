/**
 * Markdown — lightweight markdown renderer for chat messages.
 *
 * Supports: headings, bold/italic, inline code, code blocks (with syntax
 * highlighting), links, lists, tables, blockquotes, and horizontal rules.
 *
 * Designed for streaming: renders incrementally without full-document re-parse.
 */

import React, { useMemo } from "react";
import { invoke } from "@tauri-apps/api/core";
import { colors, typo, radius, space } from "../design";
import { toast } from "./Toast";


// Tokenizer


type InlineToken =
  | { type: "text"; content: string }
  | { type: "bold"; content: InlineToken[] }
  | { type: "italic"; content: InlineToken[] }
  | { type: "code"; content: string }
  | { type: "link"; content: InlineToken[]; url: string }
  | { type: "br" };

type Block =
  | { type: "paragraph"; tokens: InlineToken[] }
  | { type: "heading"; level: number; tokens: InlineToken[] }
  | { type: "code_block"; language: string; code: string }
  | { type: "list"; ordered: boolean; items: InlineToken[][]; start?: number }
  | { type: "blockquote"; blocks: Block[] }
  | { type: "table"; header: InlineToken[][]; rows: InlineToken[][][] }
  | { type: "hr" }
  | { type: "empty" };

export type LinkTargetKind = "web" | "workspace" | "blocked";

export function classifyLinkTarget(target: string): LinkTargetKind {
  const value = String(target || "").trim();
  if (!value || /[\u0000-\u001f\u007f]/.test(value)) return "blocked";
  if (/^[A-Za-z]:[\\/]/.test(value) || value.startsWith("\\\\")) return "workspace";
  try {
    const parsed = new URL(value);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") return "web";
    return "blocked";
  } catch {
    if (/^(?:data|blob|javascript|file):/i.test(value)) return "blocked";
    return "workspace";
  }
}

async function openLinkTarget(target: string): Promise<void> {
  try {
    await invoke("open_safe_target", { target });
  } catch (error) {
    toast.error("Link blocked", error instanceof Error ? error.message : String(error));
  }
}

// Simple inline parser — handles bold, italic, code, links
function parseInline(line: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  let i = 0;

  while (i < line.length) {
    // Bold **...**
    if (line[i] === "*" && line[i + 1] === "*") {
      i += 2;
      const end = line.indexOf("**", i);
      if (end !== -1) {
        tokens.push({ type: "bold", content: parseInline(line.slice(i, end)) });
        i = end + 2;
        continue;
      }
    }

    // Italic *...*  (but not **)
    if (line[i] === "*" && line[i + 1] !== "*") {
      i += 1;
      const end = line.indexOf("*", i);
      if (end !== -1) {
        tokens.push({ type: "italic", content: parseInline(line.slice(i, end)) });
        i = end + 1;
        continue;
      }
    }

    // Inline code `...`
    if (line[i] === "`") {
      i += 1;
      const end = line.indexOf("`", i);
      if (end !== -1) {
        tokens.push({ type: "code", content: line.slice(i, end) });
        i = end + 1;
        continue;
      }
    }

    // Link [text](url)
    if (line[i] === "[") {
      const closeBracket = line.indexOf("](", i);
      if (closeBracket !== -1) {
        const closeParen = line.indexOf(")", closeBracket + 2);
        if (closeParen !== -1) {
          const text = line.slice(i + 1, closeBracket);
          const url = line.slice(closeBracket + 2, closeParen);
          tokens.push({ type: "link", content: parseInline(text), url });
          i = closeParen + 1;
          continue;
        }
      }
    }

    // Collect plain text until next special char
    let j = i;
    while (j < line.length && !"*`[".includes(line[j])) j++;
    if (j > i) {
      tokens.push({ type: "text", content: line.slice(i, j) });
      i = j;
    } else {
      // Single character, skip
      tokens.push({ type: "text", content: line[i] });
      i++;
    }
  }

  return tokens;
}


// Block parser


function parseBlocks(text: string): Block[] {
  const lines = text.split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Empty line
    if (line.trim() === "") {
      blocks.push({ type: "empty" });
      i++;
      continue;
    }

    // Code block ```
    if (line.trim().startsWith("```")) {
      const language = line.trim().slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      blocks.push({ type: "code_block", language, code: codeLines.join("\n") });
      i++; // skip closing ```
      continue;
    }

    // Heading
    const headingMatch = line.match(/^(#{1,6})\s+(.+)/);
    if (headingMatch) {
      blocks.push({ type: "heading", level: headingMatch[1].length, tokens: parseInline(headingMatch[2]) });
      i++;
      continue;
    }

    // Horizontal rule
    if (/^(-{3,}|_{3,}|\*{3,})\s*$/.test(line.trim())) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    // Blockquote
    if (line.startsWith("> ")) {
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].startsWith("> ")) {
        quoteLines.push(lines[i].slice(2));
        i++;
      }
      blocks.push({ type: "blockquote", blocks: parseBlocks(quoteLines.join("\n")) });
      continue;
    }

    // Unordered list
    if (/^[\*\-\+]\s+/.test(line)) {
      const items: InlineToken[][] = [];
      while (i < lines.length && /^[\*\-\+]\s+/.test(lines[i])) {
        items.push(parseInline(lines[i].replace(/^[\*\-\+]\s+/, "")));
        i++;
      }
      blocks.push({ type: "list", ordered: false, items });
      continue;
    }

    // Ordered list
    if (/^\d+\.\s+/.test(line)) {
      const items: InlineToken[][] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(parseInline(lines[i].replace(/^\d+\.\s+/, "")));
        i++;
      }
      blocks.push({ type: "list", ordered: true, items });
      continue;
    }

    // Table detection — at least 2 lines, second is separator
    if (line.includes("|") && i + 1 < lines.length && lines[i + 1].includes("---")) {
      const headerCells = line.split("|").filter(c => c.trim()).map(c => parseInline(c.trim()));
      i += 2; // skip separator
      const rows: InlineToken[][][] = [];
      while (i < lines.length && lines[i].includes("|")) {
        rows.push(lines[i].split("|").filter(c => c.trim()).map(c => parseInline(c.trim())));
        i++;
      }
      blocks.push({ type: "table", header: headerCells, rows });
      continue;
    }

    // Regular paragraph — join consecutive non-empty non-special lines
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trim().startsWith("```") &&
      !lines[i].match(/^(#{1,6})\s+/) &&
      !lines[i].startsWith("> ") &&
      !/^[\*\-\+]\s+/.test(lines[i]) &&
      !/^\d+\.\s+/.test(lines[i]) &&
      !/^(-{3,}|_{3,}|\*{3,})\s*$/.test(lines[i].trim()) &&
      !(lines[i].includes("|") && i + 1 < lines.length && lines[i + 1].includes("---"))
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    const joined = paraLines.join("\n");
    const ptokens = parseInline(joined);
    blocks.push({ type: "paragraph", tokens: ptokens });
  }

  return blocks;
}


// Keyword syntax highlighting (code blocks)


const KEYWORDS = /\b(?:def|class|import|from|return|if|else|elif|for|while|try|except|finally|with|as|async|await|yield|raise|pass|break|continue|and|or|not|in|is|lambda|None|True|False|self|print|let|const|var|function|export|default|type|interface|enum|implements|extends|new|this|super|throw|catch|namespace|package|public|private|protected|static|final|abstract|int|float|str|bool|list|dict|tuple|set|void|string|number|boolean|any|unknown|never|readonly|keyof|typeof)\b/g;
const STRING_LITERAL = /(["'`])(?:(?!\1)[^\\]|\\.)*\1/g;
const COMMENT_LINE = /(#|\/\/).*$/gm;
const NUMBER_LIT = /\b\d+\.?\d*\b/g;

function highlightCode(code: string, language: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  // Combine patterns
  const combined = new RegExp(
    `(${KEYWORDS.source})|(${STRING_LITERAL.source})|(${COMMENT_LINE.source})|(${NUMBER_LIT.source})`,
    "gm",
  );

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = combined.exec(code)) !== null) {
    // Text before match
    if (match.index > lastIndex) {
      parts.push(code.slice(lastIndex, match.index));
    }

    if (match[1]) {
      // Keyword
      parts.push(
        <span key={match.index} style={{ color: colors.accent, fontWeight: typo.semibold }}>
          {match[1]}
        </span>,
      );
    } else if (match[2]) {
      // String
      parts.push(
        <span key={match.index} style={{ color: colors.success }}>
          {match[2]}
        </span>,
      );
    } else if (match[3]) {
      // Comment
      parts.push(
        <span key={match.index} style={{ color: colors.textTertiary, fontStyle: "italic" }}>
          {match[3]}
        </span>,
      );
    } else if (match[4]) {
      // Number
      parts.push(
        <span key={match.index} style={{ color: colors.warning }}>
          {match[4]}
        </span>,
      );
    }

    lastIndex = combined.lastIndex;
  }

  // Remaining text
  if (lastIndex < code.length) {
    parts.push(code.slice(lastIndex));
  }

  return parts;
}


// Renderers


function RenderInline({ tokens }: { tokens: InlineToken[] }): React.ReactNode {
  return tokens.map((token, i) => {
    switch (token.type) {
      case "text":
        return token.content;
      case "bold":
        return (
          <strong key={i} style={{ fontWeight: typo.bold }}>
            <RenderInline tokens={token.content} />
          </strong>
        );
      case "italic":
        return (
          <em key={i}>
            <RenderInline tokens={token.content} />
          </em>
        );
      case "code":
        return (
          <code
            key={i}
            style={{
              fontFamily: typo.mono,
              fontSize: "0.9em",
              background: colors.inlineCodeBg,
              padding: "1px 5px",
              borderRadius: radius.sm,
              color: colors.text,
            }}
          >
            {token.content}
          </code>
        );
      case "link":
        if (classifyLinkTarget(token.url) === "blocked") {
          return (
            <span key={i} title="Blocked unsafe link" style={{ color: colors.textTertiary, textDecoration: "line-through" }}>
              <RenderInline tokens={token.content} />
            </span>
          );
        }
        return (
          <a
            key={i}
            href="#"
            onClick={(event) => {
              event.preventDefault();
              void openLinkTarget(token.url);
            }}
            style={{ color: colors.accent, textDecoration: "underline" }}
          >
            <RenderInline tokens={token.content} />
          </a>
        );
      default:
        return null;
    }
  });
}

function RenderBlock({ block }: { block: Block }): React.ReactNode {
  switch (block.type) {
    case "empty":
      return <div style={{ height: space.sm }} />;

    case "paragraph":
      return (
        <p style={{ margin: `${space.xs} 0`, lineHeight: typo.relaxed }}>
          <RenderInline tokens={block.tokens} />
        </p>
      );

    case "heading": {
      const sizes: Record<number, string> = { 1: typo.xxl, 2: typo.xl, 3: typo.lg, 4: typo.md, 5: typo.base, 6: typo.sm };
      return (
        <div
          style={{
            fontSize: sizes[block.level] || typo.md,
            fontWeight: typo.semibold,
            margin: `${space.md} 0 ${space.xs} 0`,
            color: colors.text,
            lineHeight: typo.tight,
          }}
        >
          <RenderInline tokens={block.tokens} />
        </div>
      );
    }

    case "code_block":
      return (
        <div
          style={{
            margin: `${space.sm} 0`,
            borderRadius: radius.md,
            background: colors.codeBg,
            border: `1px solid ${colors.border}`,
            overflow: "hidden",
          }}
        >
          {block.language && (
            <div
              style={{
                padding: `${space.xs} ${space.md}`,
                fontSize: typo.xs,
                color: colors.textTertiary,
                fontFamily: typo.mono,
                borderBottom: `1px solid ${colors.border}`,
                background: colors.surfaceHover,
              }}
            >
              {block.language}
            </div>
          )}
          <pre
            style={{
              margin: 0,
              padding: space.md,
              fontSize: typo.sm,
              fontFamily: typo.mono,
              color: colors.codeText,
              lineHeight: typo.relaxed,
              overflowX: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            <code>{highlightCode(block.code, block.language)}</code>
          </pre>
        </div>
      );

    case "list":
      return (
        <ul
          style={{
            margin: `${space.xs} 0`,
            paddingLeft: space.xl,
            listStyle: block.ordered ? "decimal" : "disc",
          }}
        >
          {block.items.map((item, i) => (
            <li key={i} style={{ marginBottom: space.xs, lineHeight: typo.relaxed }}>
              <RenderInline tokens={item} />
            </li>
          ))}
        </ul>
      );

    case "blockquote":
      return (
        <blockquote
          style={{
            margin: `${space.sm} 0`,
            paddingLeft: space.md,
            borderLeft: `3px solid ${colors.accent}`,
            color: colors.textSecondary,
          }}
        >
          {block.blocks.map((b, i) => (
            <RenderBlock key={i} block={b} />
          ))}
        </blockquote>
      );

    case "table":
      return (
        <div style={{ margin: `${space.sm} 0`, overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: typo.sm,
            }}
          >
            <thead>
              <tr>
                {block.header.map((cell, i) => (
                  <th
                    key={i}
                    style={{
                      padding: `${space.xs} ${space.sm}`,
                      borderBottom: `2px solid ${colors.border}`,
                      textAlign: "left",
                      fontWeight: typo.semibold,
                    }}
                  >
                    <RenderInline tokens={cell} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, ri) => (
                <tr key={ri}>
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      style={{
                        padding: `${space.xs} ${space.sm}`,
                        borderBottom: `1px solid ${colors.borderLight}`,
                      }}
                    >
                      <RenderInline tokens={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );

    case "hr":
      return (
        <hr
          style={{
            border: "none",
            borderTop: `1px solid ${colors.border}`,
            margin: `${space.md} 0`,
          }}
        />
      );

    default:
      return null;
  }
}


// Main Component


export function Markdown({ content }: { content: string }) {
  const blocks = useMemo(() => parseBlocks(content), [content]);

  return (
    <div style={{ wordBreak: "break-word" }}>
      {blocks.map((block, i) => (
        <RenderBlock key={i} block={block} />
      ))}
    </div>
  );
}

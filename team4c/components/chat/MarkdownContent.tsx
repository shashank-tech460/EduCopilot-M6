"use client";

import { isValidElement, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";

interface MarkdownContentProps {
  content: string;
}

/**
 * Markdown_Content — Phase 6B (Team4C core product completion).
 *
 * Renders a chat message's text as Markdown instead of a raw joined
 * string. Real Team4B answers can contain headings, bold text, numbered
 * steps, bullet lists, inline code, fenced code blocks, and tables (see
 * docs/RAG_VALIDATION.md's live-tested answer examples) — plain-text
 * rendering discarded all of that structure.
 *
 * SECURITY (Phase 6B requirement — assistant/LLM output is untrusted
 * content, same trust boundary Team4B's own `llm_generator.py` already
 * treats retrieved context as data, never instructions):
 *   - `react-markdown` parses Markdown into a syntax tree and renders it
 *     through React elements it constructs itself — it never calls
 *     `dangerouslySetInnerHTML` and has no code path that executes a
 *     string as HTML/JS, by construction (confirmed: this component does
 *     not import or use `rehype-raw`, `rehype-sanitize`, or any HTML-
 *     interpreting plugin — with no such plugin, literal HTML/script
 *     tags in the input Markdown are not parsed as HTML at all; they are
 *     rendered as inert, escaped text, exactly like any other character
 *     sequence). This is `react-markdown`'s documented default behavior,
 *     not a configuration this component has to enforce itself.
 *   - Links render through a custom `a` component that always sets
 *     `target="_blank" rel="noopener noreferrer"` (no `window.opener`
 *     access, no implicit trust of the link's own referrer) and
 *     `break-words` so a long/malicious URL cannot force horizontal
 *     page overflow.
 *   - Nothing here changes citation rendering — `SourceAttribution`
 *     (components/chat/SourceAttribution.tsx) is untouched and continues
 *     to render from `message.parts`' own `data-citations` entries,
 *     completely independent of this component.
 *
 * Kept deliberately small: no syntax highlighting library, no math
 * rendering, no raw-HTML escape hatch — `remark-gfm` (tables, strikethrough,
 * task lists, autolinks) is the only plugin, matching the "don't make the
 * renderer excessively complex" instruction while still covering every
 * Markdown construct a real grounded answer has been observed to use.
 */
/** Recursively flattens a React node tree back into its plain-text content. */
function extractText(node: React.ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(extractText).join("");
  }
  if (isValidElement<{ children?: React.ReactNode }>(node)) {
    return extractText(node.props.children);
  }
  return "";
}

/** Reads the `language-xxx` class remark attaches to a fenced code block's language tag, if any. */
function extractLanguage(node: React.ReactNode): string | null {
  if (isValidElement<{ className?: string }>(node)) {
    const match = /language-(\w+)/.exec(node.props.className ?? "");
    return match ? match[1] : null;
  }
  return null;
}

/**
 * Fenced-code-block chrome: a small header showing the detected language
 * (when the answer's Markdown includes one, e.g. ```python) and a copy
 * button, above the actual <pre><code> content. Purely a presentation
 * wrapper — `children` (the real <code> element remark/react-markdown
 * produced) is rendered completely unchanged beneath it, so the existing
 * XSS-safety guarantees (no dangerouslySetInnerHTML, no rehype-raw) are
 * untouched.
 */
function CodeBlock({ children }: { children?: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const language = extractLanguage(children);
  const text = extractText(children);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access can fail (unsupported browser, denied permission,
      // insecure context) -- silently no-op rather than showing an error
      // for a purely convenience affordance.
    }
  }

  return (
    <div className="mt-1 overflow-hidden rounded-md bg-black/85 dark:bg-black/60">
      <div className="flex items-center justify-between gap-2 border-b border-white/10 px-2.5 py-1">
        <span className="font-mono text-[0.7rem] uppercase tracking-wide text-white/50">
          {language ?? "code"}
        </span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[0.7rem] text-white/60 transition-colors hover:bg-white/10 hover:text-white/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/40"
        >
          {copied ? <Check className="h-3 w-3" aria-hidden="true" /> : <Copy className="h-3 w-3" aria-hidden="true" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-2.5 text-xs leading-relaxed text-white">{children}</pre>
    </div>
  );
}

const markdownComponents: Components = {
  // Phase 6I: paragraph/list/heading spacing loosened slightly (2px list
  // gaps read as a wall of text at real chat width) — still restrained,
  // not double-spaced, per the "adequate spacing, not excessive" brief.
  p: ({ children }) => <p className="whitespace-pre-wrap [&:not(:first-child)]:mt-2.5">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => <ul className="mt-1.5 list-disc space-y-1.5 pl-5 marker:text-brand-indigo/70">{children}</ul>,
  ol: ({ children }) => <ol className="mt-1.5 list-decimal space-y-1.5 pl-5 marker:font-medium marker:text-brand-indigo">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed [&>p]:inline [&>p:not(:first-child)]:block">{children}</li>,
  // Headings get a real size step (h1/h2 a touch larger than body, h3+
  // hold at body size but stay bold) so "## Main concepts" reads as an
  // actual section break, not just bolded body text — the "multiple
  // distinct sections" case from the formatting brief. A hairline top
  // border on h2 (when it isn't the very first thing in the bubble)
  // gives the subtle section separation the brief asks for, without a
  // heavy divider.
  h1: ({ children }) => (
    <h1 className="mt-3 text-[0.95rem] font-semibold tracking-tight first:mt-0">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-4 border-t border-border/60 pt-3 text-[0.9rem] font-semibold tracking-tight first:mt-0 first:border-t-0 first:pt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => <h3 className="mt-3 text-sm font-semibold first:mt-0">{children}</h3>,
  h4: ({ children }) => <h4 className="mt-2.5 text-sm font-semibold first:mt-0">{children}</h4>,
  h5: ({ children }) => <h5 className="mt-2.5 text-sm font-semibold first:mt-0">{children}</h5>,
  h6: ({ children }) => <h6 className="mt-2.5 text-sm font-semibold first:mt-0">{children}</h6>,
  blockquote: ({ children }) => (
    <blockquote className="mt-2 border-l-2 border-brand-indigo/40 pl-3 italic text-muted-foreground">
      {children}
    </blockquote>
  ),
  // Fenced/indented code blocks are always wrapped in <pre><code> by
  // remark -- this is the only place block-level code styling (overflow
  // handling so a long line never breaks the mobile layout) needs to
  // apply. The nested `code` override below stays visually minimal so it
  // doesn't double up on background/padding inside this wrapper.
  pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
  // Covers BOTH inline code ("`like this`", never inside a <pre>) and the
  // text content of a fenced block (nested inside the `pre` override
  // above, which already supplies the block background/scroll handling).
  // A single style that reads reasonably in both places keeps this
  // component small, per the "don't make the renderer excessively
  // complex" instruction.
  code: ({ children }) => (
    <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
  ),
  a: ({ href, children }) => (
    // Inherits the surrounding bubble's own text color (user bubbles use
    // `text-primary-foreground`, assistant bubbles the default foreground)
    // rather than forcing `text-primary`, which would be low-contrast
    // against a `bg-primary` user bubble -- underline is the visual cue.
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="break-words underline underline-offset-2 opacity-90 hover:opacity-100"
    >
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="mt-1 overflow-x-auto">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="border-b">{children}</thead>,
  th: ({ children }) => <th className="px-2 py-1 text-left font-semibold">{children}</th>,
  td: ({ children }) => <td className="border-t px-2 py-1 align-top">{children}</td>,
  hr: () => <hr className="my-2 border-muted-foreground/20" />,
};

export function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <div className="text-sm leading-relaxed [&>*:first-child]:mt-0 break-words">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

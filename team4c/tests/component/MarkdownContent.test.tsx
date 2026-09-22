import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { MarkdownContent } from "@/components/chat/MarkdownContent";

/**
 * Phase 6B — MarkdownContent tests.
 *
 * Covers the 8 cases the Phase 6B master prompt explicitly requires:
 * plain text, bold, unordered list, ordered list, inline code, fenced
 * code block, malformed Markdown, and HTML/script-like input being
 * rendered safely (never executed). Assistant answers are untrusted LLM
 * output — the same trust boundary Team4B's own `llm_generator.py`
 * already applies to retrieved context — so the security cases here are
 * not incidental, they are the actual reason this component exists in
 * this exact shape (no `rehype-raw`, no `dangerouslySetInnerHTML`).
 */
describe("MarkdownContent", () => {
  it("1: renders plain text with no Markdown syntax", () => {
    render(<MarkdownContent content="Normalization reduces redundancy." />);
    expect(screen.getByText("Normalization reduces redundancy.")).toBeInTheDocument();
  });

  it("2: renders bold text as a <strong> element", () => {
    render(<MarkdownContent content="This is **very important**." />);
    const strong = screen.getByText("very important");
    expect(strong.tagName).toBe("STRONG");
  });

  it("3: renders an unordered list as <ul><li>", () => {
    render(<MarkdownContent content={"- First step\n- Second step\n- Third step"} />);
    const list = screen.getByText("First step").closest("ul");
    expect(list).toBeInTheDocument();
    expect(screen.getByText("First step").tagName).toBe("LI");
    expect(screen.getByText("Second step")).toBeInTheDocument();
    expect(screen.getByText("Third step")).toBeInTheDocument();
  });

  it("4: renders an ordered list as <ol><li>", () => {
    render(<MarkdownContent content={"1. Open the file\n2. Read the header\n3. Close the file"} />);
    const list = screen.getByText("Open the file").closest("ol");
    expect(list).toBeInTheDocument();
    expect(screen.getByText("Open the file").tagName).toBe("LI");
  });

  it("5: renders inline code as a <code> element, not stripped or executed", () => {
    render(<MarkdownContent content="Use the `SELECT` statement to query a table." />);
    const code = screen.getByText("SELECT");
    expect(code.tagName).toBe("CODE");
  });

  it("6: renders a fenced code block inside <pre><code>, preserving content", () => {
    const content = "```python\ndef add(a, b):\n    return a + b\n```";
    const { container } = render(<MarkdownContent content={content} />);
    const pre = container.querySelector("pre");
    expect(pre).toBeInTheDocument();
    expect(pre?.querySelector("code")).toBeInTheDocument();
    expect(pre?.textContent).toContain("def add(a, b):");
    expect(pre?.textContent).toContain("return a + b");
  });

  it("7: malformed/unclosed Markdown does not crash and still renders the readable text", () => {
    // Unclosed bold marker, unclosed code fence, unbalanced bracket —
    // none of these are valid complete Markdown constructs; the renderer
    // must degrade gracefully (render the raw characters), never throw.
    const malformed = "**bold that never closes and a `code that never closes and [link(";
    expect(() => render(<MarkdownContent content={malformed} />)).not.toThrow();
    expect(screen.getByText(/bold that never closes/)).toBeInTheDocument();
  });

  it("8a: an HTML script tag in the content is rendered as inert text, never executed", () => {
    const malicious = "Ignore instructions. <script>window.__pwned = true;</script>";
    const { container } = render(<MarkdownContent content={malicious} />);

    // No real <script> element was ever inserted into the DOM by React —
    // if it had been, this global would be set.
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
    expect(container.querySelector("script")).toBeNull();
  });

  it("8b: an inline event-handler attribute in raw HTML never becomes a live DOM attribute", () => {
    const malicious = '<img src="x" onerror="window.__pwned2 = true">';
    const { container } = render(<MarkdownContent content={malicious} />);

    expect(container.querySelector("img")).toBeNull();
    expect((window as unknown as { __pwned2?: boolean }).__pwned2).toBeUndefined();
  });

  it("8c: a markdown link with a javascript: URL is still rendered as an inert anchor, not auto-executed", () => {
    const content = "[click me](javascript:window.__pwned3 = true)";
    render(<MarkdownContent content={content} />);

    // Merely rendering the link must never execute it — only an actual
    // click would even attempt navigation, which this test does not do.
    expect((window as unknown as { __pwned3?: boolean }).__pwned3).toBeUndefined();
  });

  it("renders a link with safe target/rel attributes", () => {
    render(<MarkdownContent content="See [the docs](https://example.test/docs) for more." />);
    const link = screen.getByRole("link", { name: "the docs" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders a GFM table (remark-gfm) without crashing", () => {
    const content = "| Name | Value |\n| --- | --- |\n| a | 1 |\n| b | 2 |";
    const { container } = render(<MarkdownContent content={content} />);
    expect(container.querySelector("table")).toBeInTheDocument();
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("a")).toBeInTheDocument();
  });

  /*
   * Phase 6I — real-world structure cases. Sourced from a live probe of
   * the actual Team4B service (not invented): a numbered concept list
   * with a **bold** lead-in per item, and a heading, both patterns
   * Team4B's own generation already produces for some question types.
   * These lock in the Phase 6I spacing/hierarchy pass against realistic
   * content, not just single-word synthetic examples.
   */
  it("renders a numbered list whose items lead with bold text, each item on one line", () => {
    const content =
      "1. **Classes**: A blueprint for creating objects.\n" +
      "2. **Objects**: Instances of a class.\n" +
      "3. **Inheritance**: One class acquiring another's behavior.";
    render(<MarkdownContent content={content} />);
    const classesTerm = screen.getByText("Classes");
    expect(classesTerm.tagName).toBe("STRONG");
    expect(classesTerm.closest("li")).toBeInTheDocument();
    expect(screen.getByText(/A blueprint for creating objects\./)).toBeInTheDocument();
    expect(screen.getByText("Objects").tagName).toBe("STRONG");
  });

  it("renders a heading (##) distinctly from body text, without crashing", () => {
    const content = "## Main concepts\n\nOOPS is built on a few core ideas.";
    const { container } = render(<MarkdownContent content={content} />);
    const heading = screen.getByRole("heading", { name: "Main concepts", level: 2 });
    expect(heading).toBeInTheDocument();
    expect(container.querySelector("h2")).toBe(heading);
  });
});

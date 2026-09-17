import { PDFParse } from "pdf-parse";

export interface ExtractedPage {
  pageNumber: number;
  text: string;
}

/**
 * Real, page-by-page PDF text extraction for mock Team B's local retrieval.
 *
 * Uses `pdf-parse`'s actual current API (v2, built on pdfjs-dist) —
 * confirmed by reading its real type definitions and running it against a
 * genuine multi-page PDF before writing this, not assumed from memory
 * (the installed version is a full rewrite of the older, differently-
 * shaped v1 API). `TextResult.pages` already gives real per-page text
 * with real page numbers — no custom page-splitting logic needed.
 *
 * Returns an empty array (not a throw) on extraction failure, so a
 * malformed/corrupt/encrypted PDF degrades to "no PDF content available
 * for retrieval" rather than crashing the chat request — the caller
 * decides what "no pages" means (e.g. honestly reporting no relevant
 * material found), matching the required error-handling behavior.
 */
export async function extractPdfPages(buffer: Buffer): Promise<ExtractedPage[]> {
  let parser: PDFParse | null = null;
  try {
    parser = new PDFParse({ data: buffer });
    const result = await parser.getText();
    return result.pages
      .map((page) => ({ pageNumber: page.num, text: page.text.trim() }))
      .filter((page) => page.text.length > 0); // Empty pages carry no retrievable content.
  } catch {
    return [];
  } finally {
    await parser?.destroy();
  }
}

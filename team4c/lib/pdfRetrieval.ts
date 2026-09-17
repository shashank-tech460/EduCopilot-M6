import type { ExtractedPage } from "@/lib/pdfExtraction";

// A small, generic stopword list — not a source of retrievable knowledge
// itself, just noise to strip before scoring so common words (the, is, a)
// don't dominate the overlap score between a question and a page.
const STOPWORDS = new Set([
  "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
  "of", "in", "on", "at", "to", "for", "with", "by", "about", "as",
  "and", "or", "but", "if", "than", "that", "this", "these", "those",
  "what", "which", "who", "how", "why", "when", "where", "do", "does",
  "did", "can", "could", "will", "would", "should", "i", "you", "it",
  "we", "they", "explain", "tell", "me",
]);

function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, " ")
    .split(/\s+/)
    .filter((token) => token.length > 1 && !STOPWORDS.has(token));
}

export interface PageMatch {
  pageNumber: number;
  text: string;
  score: number;
}

interface ScorableItem {
  text: string;
}

/**
 * Generic version of the same scoring logic, over anything with a `text`
 * field — added so transcript segments (services/transcript) can reuse the
 * exact same tokenizer/scoring behavior as PDF pages, rather than
 * duplicating it. `scorePages` below is now a thin wrapper over this.
 */
function scoreItems<T extends ScorableItem>(query: string, items: T[]): (T & { score: number })[] {
  const queryTokens = new Set(tokenize(query));
  if (queryTokens.size === 0) {
    return [];
  }

  return items
    .map((item) => {
      const itemTokens = new Set(tokenize(item.text));
      let matchedTokens = 0;
      for (const token of queryTokens) {
        if (itemTokens.has(token)) {
          matchedTokens += 1;
        }
      }
      return { ...item, score: matchedTokens / queryTokens.size };
    })
    .sort((a, b) => b.score - a.score);
}

/**
 * Deterministic local retrieval — Accion Labs mock Team B, NOT a
 * production vector database or embedding search. Scores each page by how
 * many of the question's meaningful tokens actually appear in that page's
 * text (a token can only contribute once per page, so a page that repeats
 * one word many times doesn't win purely on repetition).
 *
 * Returns matches sorted best-first, all of them — callers apply their own
 * minimum-score threshold so "no page actually matches" is a real,
 * representable outcome (see MIN_RETRIEVAL_SCORE in services/teamB/mock.ts)
 * rather than always returning page 1 by default.
 */
export function scorePages(query: string, pages: ExtractedPage[]): PageMatch[] {
  return scoreItems(query, pages).map((item) => ({
    pageNumber: item.pageNumber,
    text: item.text,
    score: item.score,
  }));
}

export interface SegmentMatch {
  start: number;
  end: number;
  text: string;
  score: number;
}

/**
 * Same scoring approach, for transcript segments ({start, end, text})
 * instead of PDF pages — used by mock Team B for video/YouTube grounding.
 */
export function scoreSegments<T extends { start: number; end: number; text: string }>(
  query: string,
  segments: T[]
): SegmentMatch[] {
  return scoreItems(query, segments).map((item) => ({
    start: item.start,
    end: item.end,
    text: item.text,
    score: item.score,
  }));
}

/**
 * Finds the transcript segment whose [start, end) range actually covers a
 * given timestamp — used both for "what is being explained around 1:30"
 * (a timestamp parsed from the question) and "what is being explained
 * here" (the real current videoTimestamp). Returns null if no segment
 * covers that exact time, rather than guessing the nearest one — an
 * uncovered gap is a real, honest "no transcript for that moment" outcome.
 */
export function findSegmentAtTime<T extends { start: number; end: number }>(
  segments: T[],
  timeSeconds: number
): T | null {
  return segments.find((segment) => timeSeconds >= segment.start && timeSeconds < segment.end) ?? null;
}

/**
 * Parses a timestamp explicitly mentioned in a question, e.g. "around
 * 1:30" or "at 90 seconds" — supports MM:SS and a bare "N second(s)" form.
 * Returns null when the question doesn't actually mention a timestamp,
 * so this is never confused with "no timestamp" (null) vs "timestamp 0"
 * (a real, valid value).
 */
export function parseTimestampFromQuery(query: string): number | null {
  const colonMatch = query.match(/(\d{1,2}):(\d{2})/);
  if (colonMatch) {
    return Number(colonMatch[1]) * 60 + Number(colonMatch[2]);
  }
  const secondsMatch = query.match(/(\d+)\s*seconds?\b/i);
  if (secondsMatch) {
    return Number(secondsMatch[1]);
  }
  return null;
}

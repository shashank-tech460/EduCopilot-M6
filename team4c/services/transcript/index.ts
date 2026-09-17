import type { TranscriptProvider } from "@/types/transcript";
import { mockTranscriptProvider } from "./mock";

/**
 * The only import path the rest of the app should use for transcripts
 * (same convention as services/teamA/index.ts and services/teamB/index.ts).
 *
 * There is no "real" provider yet — unlike Team A/B, transcripts aren't
 * part of any external team's contract at all; a real implementation here
 * would be this project's own future work (real STT, or YouTube's caption
 * API), not something to invent now. Always returns the mock, but kept as
 * a function (not a direct export of the mock) so a real provider can
 * replace it later without touching any caller.
 */
export function getTranscriptProvider(): TranscriptProvider {
  return mockTranscriptProvider;
}

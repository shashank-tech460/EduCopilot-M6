import { randomUUID } from "crypto";

import type {
  TeamAService,
  TeamASubmitContext,
  TeamASubmitRequest,
  TeamASubmitResponse,
  TeamAStatusResponse,
} from "@/types/teamA";

/**
 * Mock Team A, used whenever USE_MOCK_TEAM_A is not explicitly "false"
 * (see services/teamA/index.ts). Makes no network call whatsoever — this is
 * verified directly by a Phase 6 test, not just implied by the code.
 *
 * Deterministic on purpose: `submit()` always succeeds, and `checkStatus()`
 * always immediately reports "ready". A real ingestion pipeline would take
 * time and could fail, but a mock that's flaky or slow makes the rest of
 * the upload flow (and its tests) needlessly hard to write and verify. If a
 * later phase specifically needs to exercise the "processing" or "failed"
 * paths in the UI, that's a deliberate, separate addition — not something
 * this mock should introduce speculatively now.
 */
export const mockTeamA: TeamAService = {
  async submit(request: TeamASubmitRequest, context: TeamASubmitContext): Promise<TeamASubmitResponse> {
    void request;
    void context; // the mock makes no network call, so it needs no JWT/identity context
    return { ingestionId: `mock-${randomUUID()}` };
  },

  async checkStatus(ingestionId: string): Promise<TeamAStatusResponse> {
    void ingestionId;
    return { status: "ready", error: null };
  },
};

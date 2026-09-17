import type { TeamAService } from "@/types/teamA";
import { mockTeamA } from "./mock";
import { realTeamA } from "./client";

/**
 * The only import path the rest of the app is allowed to use for Team A
 * (docs/decisions.md §2/§6). Upload routes call getTeamAService() and never
 * import mock.ts or client.ts directly, so switching implementations is a
 * one-line env change, not a code change.
 *
 * getTeamAService() is a function, not a top-level constant, so
 * USE_MOCK_TEAM_A is read fresh on every call rather than captured once at
 * module-load time — this project already found and fixed exactly that bug
 * for MONGODB_URI in lib/mongodb.ts (Phase 5), so the same mistake isn't
 * repeated here.
 *
 * Defaults to the mock unless USE_MOCK_TEAM_A is explicitly the string
 * "false" — an unset or misconfigured flag fails safe into the mock rather
 * than accidentally attempting a real network call with no credentials.
 */
export function getTeamAService(): TeamAService {
  return process.env.USE_MOCK_TEAM_A === "false" ? realTeamA : mockTeamA;
}

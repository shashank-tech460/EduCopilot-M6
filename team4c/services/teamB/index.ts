import type { TeamBService } from "@/types/teamB";
import { mockTeamB } from "./mock";
import { realTeamB } from "./client";

/**
 * The only import path the rest of the app is allowed to use for Team B
 * (same convention as services/teamA/index.ts). /api/chat calls
 * getTeamBService() and never imports mock.ts or client.ts directly.
 *
 * A function, not a top-level constant, so USE_MOCK_TEAM_B is read fresh
 * on every call rather than captured once at module-load time.
 *
 * Defaults to the mock unless USE_MOCK_TEAM_B is explicitly "false" — an
 * unset or misconfigured flag fails safe into the mock.
 */
export function getTeamBService(): TeamBService {
  return process.env.USE_MOCK_TEAM_B === "false" ? realTeamB : mockTeamB;
}

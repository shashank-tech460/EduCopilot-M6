import type { TeamBAuthContext, TeamBMockOnlyContext, TeamBQueryRequest, TeamBQueryResponse, TeamBService } from "@/types/teamB";
import { loadServiceJwtSigningConfigFromEnv, mintServiceJwt } from "@/lib/serviceJwt";

/**
 * Real Team B ("Team 4b") client -- Phase 2E: authenticated canonical
 * wiring. Replaces the earlier stale, static-API-key placeholder.
 *
 * Every call mints a fresh, short-lived (Phase 2B default: 300s) ES256
 * internal service JWT from SERVER-VERIFIED identity (`request.sub`/
 * `request.workspace_id` -- see types/teamB.ts's `TeamBAuthContext`,
 * supplied by app/api/chat/route.ts from the authenticated session and
 * the already-authorized workspace, exactly mirroring
 * services/teamA/client.ts's Phase 2D pattern) -- never a client-
 * supplied or request-body value. The wire body sent to
 * `/api/v1/query` is EXACTLY `TeamBQueryRequest`
 * (`{query, session_id, retrieval_config}`) -- `workspaceId`/
 * `videoTimestamp` (TeamBMockOnlyContext, consumed only by the local
 * mock) and `sub`/`workspace_id` (TeamBAuthContext, consumed only to
 * mint the JWT) are both explicitly excluded from the serialized body
 * below, even though this function receives an object that may carry
 * all of them.
 */
export const realTeamB: TeamBService = {
  async query(
    request: TeamBQueryRequest & Partial<TeamBMockOnlyContext> & Partial<TeamBAuthContext>
  ): Promise<TeamBQueryResponse> {
    const url = requireUrl();

    if (!request.sub || !request.workspace_id) {
      // A real call MUST carry server-verified identity to mint a JWT --
      // unlike the mock-only fields (which the mock alone needs), this
      // is a hard requirement for the REAL client specifically.
      throw new Error(
        "realTeamB.query() requires sub and workspace_id (TeamBAuthContext) to mint the internal service JWT."
      );
    }

    const signingConfig = loadServiceJwtSigningConfigFromEnv();
    const token = await mintServiceJwt(signingConfig, {
      sub: request.sub,
      workspace_id: request.workspace_id,
      scope: "query",
      aud: "team4b-query",
    });

    // Explicitly serializes ONLY the three canonical fields.
    const canonicalBody: TeamBQueryRequest = {
      query: request.query,
      session_id: request.session_id,
      retrieval_config: request.retrieval_config,
    };

    const response = await fetch(`${url}/api/v1/query`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(canonicalBody),
    });

    if (!response.ok) {
      // Preserves the actual 4B status distinction (401/403/422/5xx)
      // for the caller to react to, without leaking response internals.
      throw new TeamBQueryError(response.status);
    }

    // Parses the actual 4B QueryResponse shape (answer, citations) --
    // no new response schema is invented here.
    return response.json();
  },
};

/** Carries the real HTTP status from a failed Team B call, so callers
 * (app/api/chat/route.ts) can distinguish auth/authorization/validation/
 * server failures without this client inventing its own error taxonomy. */
export class TeamBQueryError extends Error {
  constructor(public readonly status: number) {
    super(`Team B query failed with status ${status}`);
  }
}

function requireUrl(): string {
  const url = process.env.TEAM_B_API_URL;

  if (!url) {
    throw new Error(
      "TEAM_B_API_URL must be set to use the real Team B client. Set USE_MOCK_TEAM_B=true for local development."
    );
  }

  return url;
}

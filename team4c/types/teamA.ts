/**
 * Team A (ingestion) service contract.
 *
 * CANONICAL as of the Phase 2A contract freeze (Rev.4.4 §11.1 / the
 * approved cross-team architecture) -- this is no longer the tentative
 * `docs/api-contracts.md §A.5` proposal. The shape below is the frozen,
 * authoritative request body `POST /v1/ingest` accepts:
 *
 *   { document_id, file_type, file_url }
 *
 * Tenant identity (workspace_id, user_id) is DELIBERATELY ABSENT from
 * this body -- Rev.4.4 requires it come exclusively from the internal
 * service JWT, never a request field. That JWT is NOT implemented by
 * this change (see services/teamA/client.ts's own note on that) -- this
 * file only freezes what the body itself may and may not contain ahead
 * of that work.
 *
 * `TeamAService.submit()`'s single parameter is exactly this canonical
 * type -- unlike Team B's contract (types/teamB.ts), Team A's mock
 * (services/teamA/mock.ts) needs no additional local-simulation context
 * beyond what's already here, so no parallel "mock-only" extension type
 * exists for this service.
 */

/** The three approved source types, exactly as Rev.4.4 defines them --
 * distinct from 4C's own internal `File.type` values ("pdf" | "video" |
 * "youtube_url"), which remain unchanged (see `toCanonicalFileType`
 * below for the mapping between the two). */
export type TeamACanonicalFileType = "pdf" | "mp4" | "youtube";

export interface TeamASubmitRequest {
  document_id: string;
  file_type: TeamACanonicalFileType;
  file_url: string;
}

export interface TeamASubmitResponse {
  ingestionId: string;
}

export interface TeamAStatusResponse {
  status: "processing" | "ready" | "failed";
  error: string | null;
}

export interface TeamAService {
  submit(request: TeamASubmitRequest, context: TeamASubmitContext): Promise<TeamASubmitResponse>;
  checkStatus(ingestionId: string): Promise<TeamAStatusResponse>;
}

/**
 * The server-side-verified identity a caller of `submit()` already
 * established BEFORE this call -- e.g. `assertOwnership()` having
 * already confirmed the authenticated user belongs to the target
 * workspace (app/api/workspaces/[id]/files/route.ts). This is NEVER
 * part of `TeamASubmitRequest` (the canonical wire body has no identity
 * fields at all, by design) -- it exists only so the REAL client
 * (services/teamA/client.ts) has what it needs to mint the Phase 2B
 * internal service JWT for this one call. `mockTeamA` accepts and
 * ignores it, since the mock makes no network call and needs no JWT.
 */
export interface TeamASubmitContext {
  sub: string;
  workspace_id: string;
}

/**
 * Maps 4C's own internal `File.type` value (a UI/product-facing
 * distinction predating this contract, and NOT changed by this freeze --
 * `models/File.ts` is untouched) to the canonical `file_type` value the
 * ingestion contract requires.
 *
 * This is the one, explicit "service-client boundary" mapping point --
 * the internal model is kept exactly as-is (per the Phase 2A task's own
 * instruction not to blindly rename fields that would affect unrelated
 * UI behavior); only the outbound value crossing into the canonical
 * contract is translated, and only here.
 */
export function toCanonicalFileType(internalType: import("@/models/File").FileType): TeamACanonicalFileType {
  switch (internalType) {
    case "pdf":
      return "pdf";
    case "video":
      return "mp4";
    case "youtube_url":
      return "youtube";
  }
}

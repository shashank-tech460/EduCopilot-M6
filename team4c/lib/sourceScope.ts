import { Types } from "mongoose";

import { FileModel } from "@/models/File";

/**
 * MVP M6 — server-authoritative source scope validation.
 *
 * Used by BOTH `PATCH /api/conversations/[id]/scope` (validating a
 * NEWLY requested scope before persisting it) and `app/api/chat/route.ts`
 * (RE-validating an ALREADY-persisted scope at query time, since a File
 * can transition away from `ready` -- or be deleted entirely -- at any
 * point after the scope was originally set).
 *
 * SECURITY MODEL: `document_id` (`File._id`) is the ONLY identity this
 * function trusts -- never filename, storageUrl, or array position. A
 * requested ID is kept ONLY if a REAL File exists with that `_id`,
 * belonging to EXACTLY `workspaceId`, with `status === "ready"` --
 * every other case (malformed ID, nonexistent File, a File belonging to
 * a different workspace, a File that is `uploading`/`processing`/
 * `failed`) causes that one ID to be silently dropped from the
 * returned, normalized list -- never rejected with a distinguishing
 * error (which would let a client probe for the existence of another
 * workspace's document IDs), and never treated as a reason to widen the
 * scope to "search everything" (see `resolveEffectiveDocumentIds`
 * below for that half of the safety property).
 *
 * Deduplicates while preserving first-occurrence order (`["B","A","B"]`
 * → `["B","A"]`) -- stable, not sorted, matching the task's own
 * stated preference.
 */
export async function validateAndNormalizeSourceScope(
  requestedDocumentIds: string[],
  workspaceId: string
): Promise<string[]> {
  const deduped: string[] = [];
  const seen = new Set<string>();
  for (const id of requestedDocumentIds) {
    if (typeof id === "string" && id.trim() && !seen.has(id)) {
      seen.add(id);
      deduped.push(id);
    }
  }

  const validObjectIds = deduped.filter((id) => Types.ObjectId.isValid(id));
  if (validObjectIds.length === 0) {
    return [];
  }

  const readyFiles = await FileModel.find({
    _id: { $in: validObjectIds },
    workspaceId,
    status: "ready",
  }).select("_id");

  const authorizedIdSet = new Set(readyFiles.map((file) => file._id.toString()));
  return deduped.filter((id) => authorizedIdSet.has(id));
}

/**
 * MVP M6 — resolves the EFFECTIVE `document_ids` value to send to Team
 * 4B for one chat request, given the Conversation's persisted
 * `sourceScopeDocumentIds` and a fresh authorization re-check.
 *
 * `null` (no scope ever set) → `null` (workspace-wide, unchanged
 * behavior) -- re-validation is skipped entirely, since there is
 * nothing to re-validate.
 *
 * A persisted, non-null scope is ALWAYS re-validated against the
 * CURRENT File state before use -- a File selected minutes/days ago may
 * have since been deleted or left the `ready` state. If re-validation
 * narrows the scope to zero surviving IDs, the return value is `[]`
 * (Team 4B's own contract: empty list = zero candidates), NEVER `null`
 * -- an invalidated explicit selection must never silently widen back
 * to workspace-wide search.
 */
export async function resolveEffectiveDocumentIds(
  persistedScope: string[] | null | undefined,
  workspaceId: string
): Promise<string[] | null> {
  if (persistedScope === null || persistedScope === undefined) {
    return null;
  }
  if (persistedScope.length === 0) {
    return [];
  }
  return validateAndNormalizeSourceScope(persistedScope, workspaceId);
}

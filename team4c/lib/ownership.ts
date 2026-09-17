import { Types } from "mongoose";

import { WorkspaceModel, type Workspace } from "@/models/Workspace";

/**
 * Thrown when a resource doesn't exist OR belongs to a different user.
 * Deliberately a single error type for both cases — see the note below on
 * why "not found" and "not yours" must look identical to the caller.
 */
export class OwnershipError extends Error {
  constructor(message = "Not found.") {
    super(message);
    this.name = "OwnershipError";
  }
}

/**
 * Verifies that `userId` owns the workspace identified by `workspaceId`,
 * per docs/decisions.md §3/§7: "no route ever trusts a client-supplied
 * userId" and ownership is enforced through one shared helper rather than
 * re-implemented per route.
 *
 * Returns the workspace document if ownership holds. Throws OwnershipError
 * otherwise — including when the workspace simply doesn't exist, or when
 * `workspaceId` isn't a syntactically valid ObjectId. All three cases
 * return the same error deliberately: a workspace that exists but belongs
 * to another student must be indistinguishable from one that doesn't exist
 * at all, otherwise the ID space itself becomes probeable (an attacker
 * could tell "this ID belongs to *someone*" apart from "this ID is unused"
 * just from a different error message).
 */
export async function assertOwnership(
  workspaceId: string,
  userId: string
): Promise<Workspace> {
  if (!Types.ObjectId.isValid(workspaceId)) {
    throw new OwnershipError();
  }

  const workspace = await WorkspaceModel.findById(workspaceId);

  if (!workspace || workspace.userId.toString() !== userId) {
    throw new OwnershipError();
  }

  return workspace;
}

import { describe, expect, it, vi, beforeEach } from "vitest";
import { Types } from "mongoose";

import { assertOwnership, OwnershipError } from "@/lib/ownership";
import { WorkspaceModel } from "@/models/Workspace";

/**
 * assertOwnership() is tested here against a mocked WorkspaceModel.findById
 * rather than a live database — the goal of these tests is to verify the
 * *authorization logic* (does the ID match, is the workspace missing, is
 * the ID even well-formed), which doesn't require Mongoose to actually talk
 * to MongoDB. A real end-to-end check (does this work against genuine
 * documents in a live collection) is covered by the manual verification
 * pass described in the Phase 4 report, not by this file.
 */
describe("assertOwnership", () => {
  const ownerUserId = new Types.ObjectId().toString();
  const otherUserId = new Types.ObjectId().toString();
  const workspaceId = new Types.ObjectId().toString();

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns the workspace when the requesting user is the owner", async () => {
    vi.spyOn(WorkspaceModel, "findById").mockResolvedValue({
      _id: new Types.ObjectId(workspaceId),
      userId: new Types.ObjectId(ownerUserId),
      name: "DBMS",
    } as never);

    const workspace = await assertOwnership(workspaceId, ownerUserId);
    expect(workspace.name).toBe("DBMS");
  });

  it("throws OwnershipError when the workspace belongs to a different user", async () => {
    vi.spyOn(WorkspaceModel, "findById").mockResolvedValue({
      _id: new Types.ObjectId(workspaceId),
      userId: new Types.ObjectId(ownerUserId),
      name: "DBMS",
    } as never);

    await expect(assertOwnership(workspaceId, otherUserId)).rejects.toThrow(OwnershipError);
  });

  it("throws OwnershipError when the workspace does not exist", async () => {
    vi.spyOn(WorkspaceModel, "findById").mockResolvedValue(null);

    await expect(assertOwnership(workspaceId, ownerUserId)).rejects.toThrow(OwnershipError);
  });

  it("throws OwnershipError for a syntactically invalid workspace ID, without querying the database", async () => {
    const findByIdSpy = vi.spyOn(WorkspaceModel, "findById");

    await expect(assertOwnership("not-a-valid-object-id", ownerUserId)).rejects.toThrow(
      OwnershipError
    );
    expect(findByIdSpy).not.toHaveBeenCalled();
  });

  it("produces the same error for 'not found' and 'not yours' (no distinguishing message)", async () => {
    const findByIdSpy = vi.spyOn(WorkspaceModel, "findById");

    findByIdSpy.mockResolvedValueOnce(null);
    const notFoundError = await assertOwnership(workspaceId, ownerUserId).catch((e) => e);

    findByIdSpy.mockResolvedValueOnce({
      _id: new Types.ObjectId(workspaceId),
      userId: new Types.ObjectId(ownerUserId),
      name: "DBMS",
    } as never);
    const notYoursError = await assertOwnership(workspaceId, otherUserId).catch((e) => e);

    expect(notFoundError.message).toBe(notYoursError.message);
  });
});

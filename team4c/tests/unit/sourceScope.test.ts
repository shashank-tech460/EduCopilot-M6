import { describe, expect, it, vi, beforeEach } from "vitest";
import { Types } from "mongoose";

vi.mock("@/models/File", () => ({
  FileModel: { find: vi.fn() },
}));

import { FileModel } from "@/models/File";
import { validateAndNormalizeSourceScope, resolveEffectiveDocumentIds } from "@/lib/sourceScope";

const mockedFind = vi.mocked(FileModel.find);

function mongooseFindResult(files: { _id: Types.ObjectId }[]) {
  return { select: vi.fn().mockResolvedValue(files) } as never;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("validateAndNormalizeSourceScope", () => {
  it("keeps only IDs that resolve to a real, ready File in the given workspace", async () => {
    const workspaceId = new Types.ObjectId().toString();
    const readyId = new Types.ObjectId();
    mockedFind.mockReturnValue(mongooseFindResult([{ _id: readyId }]));

    const result = await validateAndNormalizeSourceScope([readyId.toString(), new Types.ObjectId().toString()], workspaceId);

    expect(result).toEqual([readyId.toString()]);
  });

  it("drops malformed (non-ObjectId) IDs without querying Mongo for them", async () => {
    const workspaceId = new Types.ObjectId().toString();
    mockedFind.mockReturnValue(mongooseFindResult([]));

    const result = await validateAndNormalizeSourceScope(["not-an-object-id", "'; DROP TABLE files; --"], workspaceId);

    expect(result).toEqual([]);
  });

  it("deduplicates while preserving first-occurrence order", async () => {
    const workspaceId = new Types.ObjectId().toString();
    const a = new Types.ObjectId();
    const b = new Types.ObjectId();
    mockedFind.mockReturnValue(mongooseFindResult([{ _id: a }, { _id: b }]));

    const result = await validateAndNormalizeSourceScope([b.toString(), a.toString(), b.toString()], workspaceId);

    expect(result).toEqual([b.toString(), a.toString()]);
  });

  it("7/8/14: a document belonging to a DIFFERENT workspace is silently dropped, never authorized", async () => {
    const workspaceId = new Types.ObjectId().toString();
    const otherWorkspaceDocId = new Types.ObjectId();
    // Mongo query itself is scoped to `workspaceId` -- a real
    // implementation would never return this row; the fake explicitly
    // returns nothing, proving the caller can't accidentally authorize it.
    mockedFind.mockReturnValue(mongooseFindResult([]));

    const result = await validateAndNormalizeSourceScope([otherWorkspaceDocId.toString()], workspaceId);

    expect(result).toEqual([]);
    expect(mockedFind).toHaveBeenCalledWith(
      expect.objectContaining({ workspaceId, status: "ready" })
    );
  });

  it("returns [] immediately (no Mongo call) when every requested ID is malformed", async () => {
    const workspaceId = new Types.ObjectId().toString();

    const result = await validateAndNormalizeSourceScope(["nope", ""], workspaceId);

    expect(result).toEqual([]);
    expect(mockedFind).not.toHaveBeenCalled();
  });
});

describe("resolveEffectiveDocumentIds", () => {
  it("null persisted scope resolves to null (workspace-wide) without querying Mongo", async () => {
    const result = await resolveEffectiveDocumentIds(null, "ws-1");

    expect(result).toBeNull();
    expect(mockedFind).not.toHaveBeenCalled();
  });

  it("undefined persisted scope (pre-M6 conversation) resolves to null", async () => {
    const result = await resolveEffectiveDocumentIds(undefined, "ws-1");

    expect(result).toBeNull();
  });

  it("11: an already-empty persisted scope resolves to [] -- never widens to null", async () => {
    const result = await resolveEffectiveDocumentIds([], "ws-1");

    expect(result).toEqual([]);
    expect(mockedFind).not.toHaveBeenCalled();
  });

  it("18/21: a persisted scope with an entry that has since become unavailable is re-validated down, never widened", async () => {
    const workspaceId = new Types.ObjectId().toString();
    const stillReady = new Types.ObjectId();
    // Mongo now returns only the still-ready one -- the deleted/failed one is gone.
    mockedFind.mockReturnValue(mongooseFindResult([{ _id: stillReady }]));

    const result = await resolveEffectiveDocumentIds(
      [stillReady.toString(), new Types.ObjectId().toString()],
      workspaceId
    );

    expect(result).toEqual([stillReady.toString()]);
  });

  it("31: when EVERY previously-selected source becomes invalid, the result is [] -- never null", async () => {
    const workspaceId = new Types.ObjectId().toString();
    mockedFind.mockReturnValue(mongooseFindResult([])); // nothing survives re-validation

    const result = await resolveEffectiveDocumentIds([new Types.ObjectId().toString()], workspaceId);

    expect(result).toEqual([]);
    expect(result).not.toBeNull();
  });
});

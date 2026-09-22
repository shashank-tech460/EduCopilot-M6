import { describe, expect, it, vi, beforeEach } from "vitest";
import { Types } from "mongoose";

/**
 * Tests the file API routes directly (real Request objects), with `auth`,
 * `connectToDatabase`, `WorkspaceModel` (used internally by the real,
 * un-mocked assertOwnership()), `FileModel`, `services/storage`, and
 * `services/teamA` all mocked. No live MongoDB connection is opened.
 * Mirrors the approach already established in tests/unit/workspaces-api.test.ts.
 */

vi.mock("@/lib/auth", () => ({
  auth: vi.fn(),
}));

vi.mock("@/lib/mongodb", () => ({
  connectToDatabase: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/models/Workspace", () => ({
  WorkspaceModel: {
    findById: vi.fn(),
  },
}));

vi.mock("@/models/File", () => ({
  FileModel: {
    find: vi.fn(),
    create: vi.fn(),
    findById: vi.fn(),
    findByIdAndDelete: vi.fn(),
  },
}));

vi.mock("@/services/storage", () => ({
  storeFile: vi.fn(),
  referenceYoutubeUrl: vi.fn(),
  deleteStoredFile: vi.fn().mockResolvedValue(undefined),
  mintLocalStorageRetrievalUrl: vi.fn(async (file: { storageUrl: string }) => file.storageUrl),
}));

vi.mock("@/services/teamA", () => ({
  getTeamAService: vi.fn(),
}));

import { auth } from "@/lib/auth";
import { WorkspaceModel } from "@/models/Workspace";
import { FileModel } from "@/models/File";
import { referenceYoutubeUrl } from "@/services/storage";
import { getTeamAService } from "@/services/teamA";
import { GET, POST } from "@/app/api/workspaces/[id]/files/route";
import { DELETE } from "@/app/api/workspaces/[id]/files/[fileId]/route";

type SimpleAuthFn = () => Promise<{
  user: { id: string; name?: string | null; email?: string | null };
  expires: string;
} | null>;

const mockedAuth = vi.mocked(auth) as unknown as ReturnType<typeof vi.fn<SimpleAuthFn>>;
const mockedWorkspaceFindById = vi.mocked(WorkspaceModel.findById);
const mockedFileFind = vi.mocked(FileModel.find);
const mockedFileCreate = vi.mocked(FileModel.create);
const mockedFileFindById = vi.mocked(FileModel.findById);
const mockedFileFindByIdAndDelete = vi.mocked(FileModel.findByIdAndDelete);
const mockedReferenceYoutubeUrl = vi.mocked(referenceYoutubeUrl);
const mockedGetTeamAService = vi.mocked(getTeamAService);

function fakeSession(userId: string) {
  return {
    user: { id: userId, name: "Sample Student", email: "sample.student@example.com" },
    expires: "2099-01-01",
  } as never;
}

function ownedWorkspace(id: string, ownerId: string) {
  return { _id: new Types.ObjectId(id), userId: new Types.ObjectId(ownerId), name: "DBMS" } as never;
}

function paramsFor(id: string) {
  return { params: Promise.resolve({ id }) };
}

function fileParamsFor(id: string, fileId: string) {
  return { params: Promise.resolve({ id, fileId }) };
}

beforeEach(() => {
  vi.clearAllMocks();
  // A deterministic fake Team A service for every test — individual tests
  // override submit()/checkStatus() only when the return value matters.
  mockedGetTeamAService.mockReturnValue({
    submit: vi.fn().mockResolvedValue({ ingestionId: "mock-test-id" }),
    checkStatus: vi.fn().mockResolvedValue({ status: "ready", error: null }),
  });
});

describe("GET /api/workspaces/[id]/files", () => {
  it("returns 401 when unauthenticated", async () => {
    mockedAuth.mockResolvedValue(null);
    const response = await GET(new Request("http://localhost"), paramsFor(new Types.ObjectId().toString()));
    expect(response.status).toBe(401);
  });

  it("returns 404 (not 403) when the workspace belongs to another user — item 9", async () => {
    const ownerId = new Types.ObjectId().toString();
    const attackerId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(attackerId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, ownerId));

    const response = await GET(new Request("http://localhost"), paramsFor(workspaceId));

    expect(response.status).toBe(404);
    expect(mockedFileFind).not.toHaveBeenCalled();
  });

  it("returns the owner's materials when the workspace belongs to them — item 8", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    const sortMock = vi.fn().mockResolvedValue([]);
    mockedFileFind.mockReturnValue({ sort: sortMock } as never);

    const response = await GET(new Request("http://localhost"), paramsFor(workspaceId));

    expect(response.status).toBe(200);
    expect(mockedFileFind).toHaveBeenCalledWith({ workspaceId });
  });

  it("safely handles a malformed workspace ID (not a valid ObjectId) — item 15", async () => {
    mockedAuth.mockResolvedValue(fakeSession(new Types.ObjectId().toString()));

    const response = await GET(new Request("http://localhost"), paramsFor("not-a-valid-id"));

    expect(response.status).toBe(404);
    expect(mockedWorkspaceFindById).not.toHaveBeenCalled();
    expect(mockedFileFind).not.toHaveBeenCalled();
  });
});

describe("POST /api/workspaces/[id]/files", () => {
  function formDataRequest(fields: Record<string, string | globalThis.File>) {
    const formData = new FormData();
    for (const [key, value] of Object.entries(fields)) {
      formData.set(key, value);
    }
    return new Request("http://localhost", { method: "POST", body: formData });
  }

  it("returns 401 when unauthenticated — item 5", async () => {
    mockedAuth.mockResolvedValue(null);
    const response = await POST(
      formDataRequest({ type: "youtube_url", youtubeUrl: "https://youtu.be/dQw4w9WgXcQ" }),
      paramsFor(new Types.ObjectId().toString())
    );
    expect(response.status).toBe(401);
  });

  it("denies upload to another user's workspace — item 7", async () => {
    const ownerId = new Types.ObjectId().toString();
    const attackerId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(attackerId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, ownerId));

    const response = await POST(
      formDataRequest({ type: "youtube_url", youtubeUrl: "https://youtu.be/dQw4w9WgXcQ" }),
      paramsFor(workspaceId)
    );

    expect(response.status).toBe(404);
    expect(mockedFileCreate).not.toHaveBeenCalled();
  });

  it("accepts a valid YouTube URL upload to the user's own workspace — item 6", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedReferenceYoutubeUrl.mockReturnValue({
      storageUrl: "https://youtu.be/dQw4w9WgXcQ",
      storageProvider: "youtube",
      publicId: "https://youtu.be/dQw4w9WgXcQ",
    });

    const createdId = new Types.ObjectId();
    const savedDoc = {
      _id: createdId,
      workspaceId,
      originalName: "https://youtu.be/dQw4w9WgXcQ",
      type: "youtube_url",
      status: "uploading",
      processingError: null,
      storageUrl: "https://youtu.be/dQw4w9WgXcQ",
      createdAt: new Date(),
      save: vi.fn().mockResolvedValue(undefined),
    };
    mockedFileCreate.mockResolvedValue(savedDoc as never);

    const response = await POST(
      formDataRequest({ type: "youtube_url", youtubeUrl: "https://youtu.be/dQw4w9WgXcQ" }),
      paramsFor(workspaceId)
    );
    const data = await response.json();

    expect(response.status).toBe(201);
    expect(data.id).toBe(createdId.toString());
    // Confirms the Team A hand-off actually ran and updated status —
    // "mock Team A hand-off works" end-to-end through the real route.
    expect(data.status).toBe("ready");
  });

  it("Phase 6G / item E — a real Team A ingestion failure (e.g. aborted_authority_lost) reaches status='failed' with an accurate processingError, not a false 'ready'", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedReferenceYoutubeUrl.mockReturnValue({
      storageUrl: "https://youtu.be/dQw4w9WgXcQ",
      storageProvider: "youtube",
      publicId: "https://youtu.be/dQw4w9WgXcQ",
    });
    // Mirrors the real client's behavior: services/teamA/client.ts's
    // realTeamA.submit() throws when Team A's canonical /v1/ingest
    // returns a non-2xx status (e.g. 409 aborted_authority_lost) --
    // confirmed live against the real service, see
    // docs/PHASE_6_LIVE_COLLECTION_ALIGNMENT.md §9.
    mockedGetTeamAService.mockReturnValue({
      submit: vi.fn().mockRejectedValue(new Error("Team A submit failed with status 409")),
      checkStatus: vi.fn(),
    });

    const savedDoc = {
      _id: new Types.ObjectId(),
      workspaceId,
      originalName: "https://youtu.be/dQw4w9WgXcQ",
      type: "youtube_url",
      status: "uploading",
      processingError: null,
      storageUrl: "https://youtu.be/dQw4w9WgXcQ",
      createdAt: new Date(),
      save: vi.fn().mockResolvedValue(undefined),
    };
    mockedFileCreate.mockResolvedValue(savedDoc as never);

    const response = await POST(
      formDataRequest({ type: "youtube_url", youtubeUrl: "https://youtu.be/dQw4w9WgXcQ" }),
      paramsFor(workspaceId)
    );
    const data = await response.json();

    expect(response.status).toBe(201); // upload itself still succeeds; ingestion status is carried in the body
    expect(data.status).toBe("failed");
    expect(data.processingError).toContain("409");
    // The in-memory document was actually mutated to reflect the real
    // failure and persisted via save() -- not silently left as "uploading"
    // or forced to "ready".
    expect(savedDoc.status).toBe("failed");
    expect(savedDoc.save).toHaveBeenCalled();
  });

  it("rejects an invalid YouTube URL with 400, without creating a file", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));

    const response = await POST(
      formDataRequest({ type: "youtube_url", youtubeUrl: "https://example.com/not-youtube" }),
      paramsFor(workspaceId)
    );

    expect(response.status).toBe(400);
    expect(mockedFileCreate).not.toHaveBeenCalled();
  });

  it("stores the file's initial status as 'uploading' before hand-off (item 12)", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedReferenceYoutubeUrl.mockReturnValue({
      storageUrl: "https://youtu.be/dQw4w9WgXcQ",
      storageProvider: "youtube",
      publicId: "https://youtu.be/dQw4w9WgXcQ",
    });
    mockedFileCreate.mockResolvedValue({
      _id: new Types.ObjectId(),
      workspaceId,
      originalName: "x",
      type: "youtube_url",
      status: "uploading",
      processingError: null,
      storageUrl: "x",
      createdAt: new Date(),
      save: vi.fn().mockResolvedValue(undefined),
    } as never);

    await POST(
      formDataRequest({ type: "youtube_url", youtubeUrl: "https://youtu.be/dQw4w9WgXcQ" }),
      paramsFor(workspaceId)
    );

    const createCallArgs = mockedFileCreate.mock.calls[0][0] as Record<string, unknown>;
    // The route relies on the schema default rather than hardcoding a
    // status itself — confirmed independently in models.test.ts. Here we
    // confirm the route doesn't override that default with something else.
    expect(createCallArgs.status).toBe("uploading");
  });

  it("safely handles a malformed workspace ID (not a valid ObjectId) — item 15", async () => {
    mockedAuth.mockResolvedValue(fakeSession(new Types.ObjectId().toString()));

    const response = await POST(
      formDataRequest({ type: "youtube_url", youtubeUrl: "https://youtu.be/dQw4w9WgXcQ" }),
      paramsFor("not-a-valid-id")
    );

    expect(response.status).toBe(404);
    expect(mockedFileCreate).not.toHaveBeenCalled();
  });
});

describe("DELETE /api/workspaces/[id]/files/[fileId]", () => {
  it("returns 401 when unauthenticated", async () => {
    mockedAuth.mockResolvedValue(null);
    const response = await DELETE(
      new Request("http://localhost"),
      fileParamsFor(new Types.ObjectId().toString(), new Types.ObjectId().toString())
    );
    expect(response.status).toBe(401);
  });

  it("deletes a material the user owns — item 10", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const fileId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedFileFindById.mockResolvedValue({
      _id: new Types.ObjectId(fileId),
      workspaceId: new Types.ObjectId(workspaceId),
      storageProvider: "local-mock",
      publicId: "abc",
    } as never);

    const response = await DELETE(new Request("http://localhost"), fileParamsFor(workspaceId, fileId));

    expect(response.status).toBe(200);
    expect(mockedFileFindByIdAndDelete).toHaveBeenCalledWith(fileId);
  });

  it("denies deleting a material when the workspace belongs to another user — item 11", async () => {
    const ownerId = new Types.ObjectId().toString();
    const attackerId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(attackerId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, ownerId));

    const response = await DELETE(
      new Request("http://localhost"),
      fileParamsFor(workspaceId, new Types.ObjectId().toString())
    );

    expect(response.status).toBe(404);
    expect(mockedFileFindByIdAndDelete).not.toHaveBeenCalled();
  });

  it("denies deleting a file that belongs to a different workspace than the one requested — item 11", async () => {
    const userId = new Types.ObjectId().toString();
    const requestedWorkspaceId = new Types.ObjectId().toString();
    const actualWorkspaceId = new Types.ObjectId().toString();
    const fileId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    // The requester DOES own the workspace they're asking about...
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(requestedWorkspaceId, userId));
    // ...but the file actually belongs to a different workspace entirely.
    mockedFileFindById.mockResolvedValue({
      _id: new Types.ObjectId(fileId),
      workspaceId: new Types.ObjectId(actualWorkspaceId),
      storageProvider: "local-mock",
      publicId: "abc",
    } as never);

    const response = await DELETE(
      new Request("http://localhost"),
      fileParamsFor(requestedWorkspaceId, fileId)
    );

    expect(response.status).toBe(404);
    expect(mockedFileFindByIdAndDelete).not.toHaveBeenCalled();
  });

  it("safely handles a malformed file ID", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));

    const response = await DELETE(
      new Request("http://localhost"),
      fileParamsFor(workspaceId, "not-a-valid-id")
    );

    expect(response.status).toBe(404);
    expect(mockedFileFindById).not.toHaveBeenCalled();
  });
});

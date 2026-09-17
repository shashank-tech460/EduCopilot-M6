import { describe, expect, it, vi, beforeEach } from "vitest";
import { Types } from "mongoose";

/**
 * These test the Route Handlers directly (calling GET/POST/DELETE with a
 * real Request object) with `auth`, `connectToDatabase`, and the Mongoose
 * model mocked — no live MongoDB connection is opened. This mirrors the
 * approach already used in tests/unit/ownership.test.ts.
 */

vi.mock("@/lib/auth", () => ({
  auth: vi.fn(),
}));

vi.mock("@/lib/mongodb", () => ({
  connectToDatabase: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/models/Workspace", () => ({
  WorkspaceModel: {
    find: vi.fn(),
    create: vi.fn(),
    findById: vi.fn(),
    findByIdAndDelete: vi.fn(),
  },
}));

/**
 * The DELETE route cascade-deletes Files, Conversations, and Messages
 * belonging to a workspace (see app/api/workspaces/[id]/route.ts's own
 * comment for the exact order/reasoning). Without these mocks, the route's
 * calls to the *real* Mongoose models hang waiting on a MongoDB connection
 * that was never established (since @/lib/mongodb is mocked to a no-op
 * above) — this is exactly what caused this test file to start timing out
 * after cascade-delete was added, rather than a bug in the route itself.
 */
vi.mock("@/models/File", () => ({
  FileModel: {
    find: vi.fn().mockResolvedValue([]),
    deleteMany: vi.fn().mockResolvedValue({ deletedCount: 0 }),
  },
}));

vi.mock("@/models/Conversation", () => ({
  ConversationModel: {
    find: vi.fn().mockResolvedValue([]),
    deleteMany: vi.fn().mockResolvedValue({ deletedCount: 0 }),
  },
}));

vi.mock("@/models/Message", () => ({
  MessageModel: {
    deleteMany: vi.fn().mockResolvedValue({ deletedCount: 0 }),
  },
}));

vi.mock("@/services/storage", () => ({
  deleteStoredFile: vi.fn().mockResolvedValue(undefined),
}));

import { auth } from "@/lib/auth";
import { WorkspaceModel } from "@/models/Workspace";
import { FileModel } from "@/models/File";
import { ConversationModel } from "@/models/Conversation";
import { MessageModel } from "@/models/Message";
import { deleteStoredFile } from "@/services/storage";
import { GET, POST } from "@/app/api/workspaces/route";
import { GET as GET_BY_ID, DELETE } from "@/app/api/workspaces/[id]/route";

/**
 * `auth` from lib/auth.ts is Auth.js's overloaded export (it can also wrap
 * route handlers/middleware, hence the broader inferred type). For these
 * tests we only ever call it as a plain `() => Promise<Session | null>`,
 * so it's cast to that narrower shape rather than fighting the overload
 * resolution on every mockResolvedValue call.
 */
type SimpleAuthFn = () => Promise<{
  user: { id: string; name?: string | null; email?: string | null };
  expires: string;
} | null>;

const mockedAuth = vi.mocked(auth) as unknown as ReturnType<typeof vi.fn<SimpleAuthFn>>;
const mockedFind = vi.mocked(WorkspaceModel.find);
const mockedCreate = vi.mocked(WorkspaceModel.create);
const mockedFindById = vi.mocked(WorkspaceModel.findById);
const mockedFindByIdAndDelete = vi.mocked(WorkspaceModel.findByIdAndDelete);
const mockedFileFind = vi.mocked(FileModel.find);
const mockedFileDeleteMany = vi.mocked(FileModel.deleteMany);
const mockedConversationFind = vi.mocked(ConversationModel.find);
const mockedConversationDeleteMany = vi.mocked(ConversationModel.deleteMany);
const mockedMessageDeleteMany = vi.mocked(MessageModel.deleteMany);
const mockedDeleteStoredFile = vi.mocked(deleteStoredFile);

function fakeSession(userId: string) {
  return {
    user: { id: userId, name: "Sample Student", email: "sample.student@example.com" },
    expires: "2099-01-01",
  } as never;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("GET /api/workspaces", () => {
  it("returns 401 when not authenticated", async () => {
    mockedAuth.mockResolvedValue(null);
    const response = await GET();
    expect(response.status).toBe(401);
  });

  it("filters by the authenticated user's ID only", async () => {
    const userId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    const sortMock = vi.fn().mockResolvedValue([]);
    mockedFind.mockReturnValue({ sort: sortMock } as never);

    await GET();

    expect(mockedFind).toHaveBeenCalledWith({ userId });
  });

  it("returns only the requesting user's own workspaces, serialized", async () => {
    const userId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    const workspaceId = new Types.ObjectId();
    const sortMock = vi.fn().mockResolvedValue([
      { _id: workspaceId, name: "DBMS", createdAt: new Date("2026-01-01") },
    ]);
    mockedFind.mockReturnValue({ sort: sortMock } as never);

    const response = await GET();
    const data = await response.json();

    expect(data).toEqual([
      { id: workspaceId.toString(), name: "DBMS", createdAt: "2026-01-01T00:00:00.000Z" },
    ]);
  });
});

describe("POST /api/workspaces", () => {
  it("returns 401 when not authenticated", async () => {
    mockedAuth.mockResolvedValue(null);
    const request = new Request("http://localhost/api/workspaces", {
      method: "POST",
      body: JSON.stringify({ name: "DBMS" }),
    });
    const response = await POST(request);
    expect(response.status).toBe(401);
  });

  it("rejects an empty workspace name with 400, without touching the database", async () => {
    mockedAuth.mockResolvedValue(fakeSession(new Types.ObjectId().toString()));
    const request = new Request("http://localhost/api/workspaces", {
      method: "POST",
      body: JSON.stringify({ name: "" }),
    });

    const response = await POST(request);

    expect(response.status).toBe(400);
    expect(mockedCreate).not.toHaveBeenCalled();
  });

  it("creates a workspace using the authenticated user's ID, never a client-supplied one", async () => {
    const sessionUserId = new Types.ObjectId().toString();
    const attackerSuppliedUserId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(sessionUserId));

    const createdId = new Types.ObjectId();
    mockedCreate.mockResolvedValue({
      _id: createdId,
      userId: sessionUserId,
      name: "DBMS",
      createdAt: new Date("2026-01-01"),
    } as never);

    const request = new Request("http://localhost/api/workspaces", {
      method: "POST",
      // Deliberately includes a userId in the body to verify it's ignored.
      body: JSON.stringify({ name: "DBMS", userId: attackerSuppliedUserId }),
    });

    const response = await POST(request);
    const data = await response.json();

    expect(response.status).toBe(201);
    expect(mockedCreate).toHaveBeenCalledWith({ userId: sessionUserId, name: "DBMS" });
    expect(data.id).toBe(createdId.toString());
  });

  it("trims the workspace name before saving", async () => {
    const userId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedCreate.mockResolvedValue({
      _id: new Types.ObjectId(),
      userId,
      name: "DBMS",
      createdAt: new Date(),
    } as never);

    const request = new Request("http://localhost/api/workspaces", {
      method: "POST",
      body: JSON.stringify({ name: "  DBMS  " }),
    });

    await POST(request);

    expect(mockedCreate).toHaveBeenCalledWith({ userId, name: "DBMS" });
  });
});

describe("GET /api/workspaces/[id]", () => {
  function paramsFor(id: string) {
    return { params: Promise.resolve({ id }) };
  }

  it("returns 401 when unauthenticated", async () => {
    mockedAuth.mockResolvedValue(null);
    const response = await GET_BY_ID(new Request("http://localhost"), paramsFor(new Types.ObjectId().toString()));
    expect(response.status).toBe(401);
  });

  it("returns the workspace when the authenticated user owns it", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedFindById.mockResolvedValue({
      _id: new Types.ObjectId(workspaceId),
      userId: new Types.ObjectId(userId),
      name: "DBMS",
      createdAt: new Date("2026-01-01"),
    } as never);

    const response = await GET_BY_ID(new Request("http://localhost"), paramsFor(workspaceId));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data).toEqual({
      id: workspaceId,
      name: "DBMS",
      createdAt: "2026-01-01T00:00:00.000Z",
    });
  });

  it("returns a safe 404 (not 403) when the workspace belongs to another user — same as DELETE's behavior", async () => {
    const ownerId = new Types.ObjectId().toString();
    const attackerId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(attackerId));
    mockedFindById.mockResolvedValue({
      _id: new Types.ObjectId(workspaceId),
      userId: new Types.ObjectId(ownerId),
      name: "DBMS",
    } as never);

    const response = await GET_BY_ID(new Request("http://localhost"), paramsFor(workspaceId));
    expect(response.status).toBe(404);
  });

  it("returns the same safe 404 for a nonexistent workspace", async () => {
    mockedAuth.mockResolvedValue(fakeSession(new Types.ObjectId().toString()));
    mockedFindById.mockResolvedValue(null);

    const response = await GET_BY_ID(
      new Request("http://localhost"),
      paramsFor(new Types.ObjectId().toString())
    );
    expect(response.status).toBe(404);
  });
});

describe("DELETE /api/workspaces/[id]", () => {
  function paramsFor(id: string) {
    return { params: Promise.resolve({ id }) };
  }

  it("returns 401 when not authenticated", async () => {
    mockedAuth.mockResolvedValue(null);
    const response = await DELETE(new Request("http://localhost"), paramsFor(new Types.ObjectId().toString()));
    expect(response.status).toBe(401);
  });

  it("deletes the workspace and cascades to its files, conversations, and messages", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedFindById.mockResolvedValue({
      _id: new Types.ObjectId(workspaceId),
      userId: new Types.ObjectId(userId),
      name: "DBMS",
    } as never);
    mockedFindByIdAndDelete.mockResolvedValue(undefined as never);

    const fileId = new Types.ObjectId();
    const conversationId = new Types.ObjectId();
    mockedFileFind.mockResolvedValue([
      { _id: fileId, storageProvider: "local-mock", publicId: "abc" },
    ] as never);
    mockedConversationFind.mockResolvedValue([{ _id: conversationId }] as never);

    const response = await DELETE(new Request("http://localhost"), paramsFor(workspaceId));

    expect(response.status).toBe(200);
    // Cascade order matters (see the route's own comment): stored bytes,
    // then File docs, then Messages (via this workspace's conversation
    // IDs), then Conversations, then the Workspace itself — verified here
    // as "were these all called with the right scoping," not strict order.
    expect(mockedDeleteStoredFile).toHaveBeenCalledWith("local-mock", "abc", workspaceId);
    expect(mockedFileDeleteMany).toHaveBeenCalledWith({ workspaceId });
    expect(mockedMessageDeleteMany).toHaveBeenCalledWith({
      conversationId: { $in: [conversationId] },
    });
    expect(mockedConversationDeleteMany).toHaveBeenCalledWith({ workspaceId });
    expect(mockedFindByIdAndDelete).toHaveBeenCalledWith(workspaceId);
  });

  it("skips message cleanup when the workspace has no conversations", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedFindById.mockResolvedValue({
      _id: new Types.ObjectId(workspaceId),
      userId: new Types.ObjectId(userId),
      name: "DBMS",
    } as never);
    mockedFindByIdAndDelete.mockResolvedValue(undefined as never);
    mockedFileFind.mockResolvedValue([] as never);
    mockedConversationFind.mockResolvedValue([] as never);

    const response = await DELETE(new Request("http://localhost"), paramsFor(workspaceId));

    expect(response.status).toBe(200);
    expect(mockedMessageDeleteMany).not.toHaveBeenCalled();
  });

  it("does not cascade-delete anything when the workspace belongs to another user", async () => {
    const ownerId = new Types.ObjectId().toString();
    const attackerId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(attackerId));
    mockedFindById.mockResolvedValue({
      _id: new Types.ObjectId(workspaceId),
      userId: new Types.ObjectId(ownerId),
      name: "DBMS",
    } as never);

    const response = await DELETE(new Request("http://localhost"), paramsFor(workspaceId));

    expect(response.status).toBe(404);
    expect(mockedFileFind).not.toHaveBeenCalled();
    expect(mockedFileDeleteMany).not.toHaveBeenCalled();
    expect(mockedConversationDeleteMany).not.toHaveBeenCalled();
    expect(mockedFindByIdAndDelete).not.toHaveBeenCalled();
  });

  it("returns a safe 404 (not 403) when the workspace belongs to another user", async () => {
    const ownerId = new Types.ObjectId().toString();
    const attackerId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(attackerId));
    mockedFindById.mockResolvedValue({
      _id: new Types.ObjectId(workspaceId),
      userId: new Types.ObjectId(ownerId),
      name: "DBMS",
    } as never);

    const response = await DELETE(new Request("http://localhost"), paramsFor(workspaceId));

    expect(response.status).toBe(404);
    expect(mockedFindByIdAndDelete).not.toHaveBeenCalled();
  });

  it("returns the same safe 404 for a nonexistent workspace", async () => {
    const userId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedFindById.mockResolvedValue(null);

    const response = await DELETE(
      new Request("http://localhost"),
      paramsFor(new Types.ObjectId().toString())
    );

    expect(response.status).toBe(404);
    expect(mockedFindByIdAndDelete).not.toHaveBeenCalled();
  });
});

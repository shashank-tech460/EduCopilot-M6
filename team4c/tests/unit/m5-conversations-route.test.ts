import { describe, expect, it, vi, beforeEach } from "vitest";
import { Types } from "mongoose";

/**
 * MVP M5 — POST /api/workspaces/[id]/conversations.
 * Mirrors the established mocking convention (tests/unit/files-api.test.ts,
 * tests/unit/chat-api.test.ts): real `auth`/`assertOwnership` logic runs,
 * `WorkspaceModel`/`ConversationModel` are mocked at the data-access layer.
 */

vi.mock("@/lib/auth", () => ({
  auth: vi.fn(),
}));

vi.mock("@/lib/mongodb", () => ({
  connectToDatabase: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/models/Workspace", () => ({
  WorkspaceModel: { findById: vi.fn() },
}));

vi.mock("@/models/Conversation", () => ({
  ConversationModel: { create: vi.fn() },
}));

import { auth } from "@/lib/auth";
import { WorkspaceModel } from "@/models/Workspace";
import { ConversationModel } from "@/models/Conversation";
import { POST } from "@/app/api/workspaces/[id]/conversations/route";

type SimpleAuthFn = () => Promise<{
  user: { id: string; name?: string | null; email?: string | null };
  expires: string;
} | null>;

const mockedAuth = vi.mocked(auth) as unknown as ReturnType<typeof vi.fn<SimpleAuthFn>>;
const mockedWorkspaceFindById = vi.mocked(WorkspaceModel.findById);
const mockedConversationCreate = vi.mocked(ConversationModel.create);

function fakeSession(userId: string) {
  return { user: { id: userId, name: "Sample Student", email: "sample.student@example.com" }, expires: "2099-01-01" } as never;
}

function ownedWorkspace(id: string, ownerId: string) {
  return { _id: new Types.ObjectId(id), userId: new Types.ObjectId(ownerId), name: "DBMS" } as never;
}

function conversationRequest(body: Record<string, unknown>) {
  return new Request("http://localhost/api/workspaces/ws/conversations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function routeParams(workspaceId: string) {
  return { params: Promise.resolve({ id: workspaceId }) };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("POST /api/workspaces/[id]/conversations", () => {
  it("1: a new conversation is created with a server-generated ragSessionId", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedConversationCreate.mockImplementation(
      (async (doc: any) => ({ _id: new Types.ObjectId(), ...doc })) as never
    );

    const response = await POST(conversationRequest({ title: "My chat" }), routeParams(workspaceId));

    expect(response.status).toBe(201);
    expect(mockedConversationCreate).toHaveBeenCalledTimes(1);
    const createdDoc = mockedConversationCreate.mock.calls[0][0] as { ragSessionId: string };
    expect(typeof createdDoc.ragSessionId).toBe("string");
    expect(createdDoc.ragSessionId.length).toBeGreaterThan(10);
  });

  it("5: the browser cannot choose ragSessionId — a body-supplied value is ignored", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedConversationCreate.mockImplementation(
      (async (doc: any) => ({ _id: new Types.ObjectId(), ...doc })) as never
    );

    await POST(conversationRequest({ title: "My chat", ragSessionId: "attacker-chosen-id" }), routeParams(workspaceId));

    const createdDoc = mockedConversationCreate.mock.calls[0][0] as { ragSessionId: string };
    expect(createdDoc.ragSessionId).not.toBe("attacker-chosen-id");
  });

  it("rejects creation for a workspace the user does not own", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(null as never);

    const response = await POST(conversationRequest({ title: "My chat" }), routeParams(workspaceId));

    expect(response.status).toBe(404);
    expect(mockedConversationCreate).not.toHaveBeenCalled();
  });

  it("returns 401 when unauthenticated", async () => {
    mockedAuth.mockResolvedValue(null);

    const response = await POST(conversationRequest({ title: "My chat" }), routeParams(new Types.ObjectId().toString()));

    expect(response.status).toBe(401);
    expect(mockedConversationCreate).not.toHaveBeenCalled();
  });

  it("two separate creation calls produce two different ragSessionIds", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedConversationCreate.mockImplementation(
      (async (doc: any) => ({ _id: new Types.ObjectId(), ...doc })) as never
    );

    await POST(conversationRequest({ title: "Chat A" }), routeParams(workspaceId));
    await POST(conversationRequest({ title: "Chat B" }), routeParams(workspaceId));

    const first = (mockedConversationCreate.mock.calls[0][0] as { ragSessionId: string }).ragSessionId;
    const second = (mockedConversationCreate.mock.calls[1][0] as { ragSessionId: string }).ragSessionId;
    expect(first).not.toBe(second);
  });
});

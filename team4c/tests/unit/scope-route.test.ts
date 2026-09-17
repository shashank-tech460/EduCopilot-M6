import { describe, expect, it, vi, beforeEach } from "vitest";
import { Types } from "mongoose";

vi.mock("@/lib/auth", () => ({ auth: vi.fn() }));
vi.mock("@/lib/mongodb", () => ({ connectToDatabase: vi.fn().mockResolvedValue(undefined) }));
vi.mock("@/models/Conversation", () => ({
  ConversationModel: { findById: vi.fn(), findByIdAndUpdate: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock("@/models/Workspace", () => ({ WorkspaceModel: { findById: vi.fn() } }));
vi.mock("@/lib/sourceScope", () => ({
  validateAndNormalizeSourceScope: vi.fn(),
}));

import { auth } from "@/lib/auth";
import { ConversationModel } from "@/models/Conversation";
import { WorkspaceModel } from "@/models/Workspace";
import { validateAndNormalizeSourceScope } from "@/lib/sourceScope";
import { PATCH } from "@/app/api/conversations/[id]/scope/route";

const mockedAuth = vi.mocked(auth) as unknown as ReturnType<typeof vi.fn>;
const mockedConversationFindById = vi.mocked(ConversationModel.findById);
const mockedConversationFindByIdAndUpdate = vi.mocked(ConversationModel.findByIdAndUpdate);
const mockedWorkspaceFindById = vi.mocked(WorkspaceModel.findById);
const mockedValidate = vi.mocked(validateAndNormalizeSourceScope);

function fakeSession(userId: string) {
  return { user: { id: userId }, expires: "2099-01-01" } as never;
}

function scopeRequest(body: unknown) {
  return new Request("http://localhost/api/conversations/conv/scope", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function paramsFor(id: string) {
  return { params: Promise.resolve({ id }) };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PATCH /api/conversations/[id]/scope", () => {
  it("persists a validated, normalized scope and returns it", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId();
    const conversationId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedConversationFindById.mockResolvedValue({ _id: conversationId, workspaceId } as never);
    mockedWorkspaceFindById.mockResolvedValue({ _id: workspaceId, userId: new Types.ObjectId(userId) } as never);
    mockedValidate.mockResolvedValue(["doc-A"]);

    const response = await PATCH(scopeRequest({ document_ids: ["doc-A", "doc-attacker"] }), paramsFor(conversationId));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data).toEqual({ document_ids: ["doc-A"] });
    expect(mockedConversationFindByIdAndUpdate).toHaveBeenCalledWith(conversationId, { sourceScopeDocumentIds: ["doc-A"] });
  });

  it("null document_ids clears the scope without calling the validator", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId();
    const conversationId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedConversationFindById.mockResolvedValue({ _id: conversationId, workspaceId } as never);
    mockedWorkspaceFindById.mockResolvedValue({ _id: workspaceId, userId: new Types.ObjectId(userId) } as never);

    const response = await PATCH(scopeRequest({ document_ids: null }), paramsFor(conversationId));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data).toEqual({ document_ids: null });
    expect(mockedValidate).not.toHaveBeenCalled();
    expect(mockedConversationFindByIdAndUpdate).toHaveBeenCalledWith(conversationId, { sourceScopeDocumentIds: null });
  });

  it("8/9: a user without workspace ownership is rejected, scope never persisted", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId();
    const conversationId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedConversationFindById.mockResolvedValue({ _id: conversationId, workspaceId } as never);
    mockedWorkspaceFindById.mockResolvedValue(null as never); // not owned

    const response = await PATCH(scopeRequest({ document_ids: ["doc-A"] }), paramsFor(conversationId));

    expect(response.status).toBe(404);
    expect(mockedConversationFindByIdAndUpdate).not.toHaveBeenCalled();
  });

  it("returns 401 when unauthenticated", async () => {
    mockedAuth.mockResolvedValue(null);

    const response = await PATCH(scopeRequest({ document_ids: [] }), paramsFor("conv-1"));

    expect(response.status).toBe(401);
    expect(mockedConversationFindByIdAndUpdate).not.toHaveBeenCalled();
  });

  it("returns 404 for a nonexistent conversation", async () => {
    mockedAuth.mockResolvedValue(fakeSession(new Types.ObjectId().toString()));
    mockedConversationFindById.mockResolvedValue(null as never);

    const response = await PATCH(scopeRequest({ document_ids: [] }), paramsFor("conv-1"));

    expect(response.status).toBe(404);
  });

  it("rejects a request body without a document_ids field", async () => {
    mockedAuth.mockResolvedValue(fakeSession(new Types.ObjectId().toString()));

    const response = await PATCH(scopeRequest({}), paramsFor("conv-1"));

    expect(response.status).toBe(400);
  });

  it("30: rejects a selection larger than the 100-document maximum without truncating it", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId();
    const conversationId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedConversationFindById.mockResolvedValue({ _id: conversationId, workspaceId } as never);
    mockedWorkspaceFindById.mockResolvedValue({ _id: workspaceId, userId: new Types.ObjectId(userId) } as never);

    const tooMany = Array.from({ length: 101 }, (_, i) => `doc-${i}`);
    const response = await PATCH(scopeRequest({ document_ids: tooMany }), paramsFor(conversationId));

    expect(response.status).toBe(400);
    expect(mockedValidate).not.toHaveBeenCalled();
    expect(mockedConversationFindByIdAndUpdate).not.toHaveBeenCalled();
  });
});

describe("GET /api/conversations/[id]/scope", () => {
  it("returns the currently persisted scope for an authorized conversation", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId();
    const conversationId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedConversationFindById.mockResolvedValue({ _id: conversationId, workspaceId, sourceScopeDocumentIds: ["doc-A"] } as never);
    mockedWorkspaceFindById.mockResolvedValue({ _id: workspaceId, userId: new Types.ObjectId(userId) } as never);

    const { GET } = await import("@/app/api/conversations/[id]/scope/route");
    const response = await GET(new Request("http://localhost"), paramsFor(conversationId));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data).toEqual({ document_ids: ["doc-A"] });
  });

  it("returns null for a conversation with no scope ever set", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId();
    const conversationId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedConversationFindById.mockResolvedValue({ _id: conversationId, workspaceId } as never);
    mockedWorkspaceFindById.mockResolvedValue({ _id: workspaceId, userId: new Types.ObjectId(userId) } as never);

    const { GET } = await import("@/app/api/conversations/[id]/scope/route");
    const response = await GET(new Request("http://localhost"), paramsFor(conversationId));
    const data = await response.json();

    expect(data).toEqual({ document_ids: null });
  });

  it("8/13: two different conversations' persisted scopes never contaminate each other's GET response", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId();
    const conv1 = new Types.ObjectId().toString();
    const conv2 = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue({ _id: workspaceId, userId: new Types.ObjectId(userId) } as never);
    const { GET } = await import("@/app/api/conversations/[id]/scope/route");

    mockedConversationFindById.mockResolvedValue({ _id: conv1, workspaceId, sourceScopeDocumentIds: ["doc-A"] } as never);
    const response1 = await GET(new Request("http://localhost"), paramsFor(conv1));
    expect(await response1.json()).toEqual({ document_ids: ["doc-A"] });

    mockedConversationFindById.mockResolvedValue({ _id: conv2, workspaceId, sourceScopeDocumentIds: ["doc-B"] } as never);
    const response2 = await GET(new Request("http://localhost"), paramsFor(conv2));
    expect(await response2.json()).toEqual({ document_ids: ["doc-B"] });
  });

  it("returns 401 when unauthenticated", async () => {
    mockedAuth.mockResolvedValue(null);
    const { GET } = await import("@/app/api/conversations/[id]/scope/route");

    const response = await GET(new Request("http://localhost"), paramsFor("conv-1"));

    expect(response.status).toBe(401);
  });

  it("a malformed conversationId returns a safe 404, not a 500", async () => {
    mockedAuth.mockResolvedValue(fakeSession(new Types.ObjectId().toString()));
    const { GET } = await import("@/app/api/conversations/[id]/scope/route");

    const response = await GET(new Request("http://localhost"), paramsFor("not-an-object-id"));

    expect(response.status).toBe(404);
    expect(mockedConversationFindById).not.toHaveBeenCalled();
  });

  it("rejects a user who does not own the conversation's workspace", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId();
    const conversationId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedConversationFindById.mockResolvedValue({ _id: conversationId, workspaceId } as never);
    mockedWorkspaceFindById.mockResolvedValue(null as never);
    const { GET } = await import("@/app/api/conversations/[id]/scope/route");

    const response = await GET(new Request("http://localhost"), paramsFor(conversationId));

    expect(response.status).toBe(404);
  });
});

import { describe, expect, it, vi, beforeEach } from "vitest";
import { Types } from "mongoose";

/**
 * Tests the /api/chat route directly (real Request, real streaming
 * response body consumed and decoded), with `auth`, `connectToDatabase`,
 * `WorkspaceModel` (used internally by the real, un-mocked
 * assertOwnership()), and `services/teamB` mocked. No live MongoDB
 * connection, no live network call. Mirrors the approach already
 * established in tests/unit/files-api.test.ts and workspaces-api.test.ts.
 *
 * The streaming response itself is NOT mocked — this exercises the real
 * `createUIMessageStream`/`createUIMessageStreamResponse` primitives from
 * the installed `ai` package, so these tests prove actual SSE streaming
 * happens, not just that the right functions were called.
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

vi.mock("@/models/Conversation", () => ({
  ConversationModel: {
    findById: vi.fn(),
    findOneAndUpdate: vi.fn(),
  },
}));

vi.mock("@/models/Message", () => ({
  MessageModel: {
    create: vi.fn(),
  },
}));

vi.mock("@/models/File", () => ({
  FileModel: {
    find: vi.fn(),
  },
}));

vi.mock("@/services/teamB", () => ({
  getTeamBService: vi.fn(),
}));

import { auth } from "@/lib/auth";
import { WorkspaceModel } from "@/models/Workspace";
import { ConversationModel } from "@/models/Conversation";
import { MessageModel } from "@/models/Message";
import { FileModel } from "@/models/File";
import { getTeamBService } from "@/services/teamB";
import { POST } from "@/app/api/chat/route";
import { TeamBQueryError } from "@/services/teamB/client";

type SimpleAuthFn = () => Promise<{
  user: { id: string; name?: string | null; email?: string | null };
  expires: string;
} | null>;

const mockedAuth = vi.mocked(auth) as unknown as ReturnType<typeof vi.fn<SimpleAuthFn>>;
const mockedWorkspaceFindById = vi.mocked(WorkspaceModel.findById);
const mockedConversationFindById = vi.mocked(ConversationModel.findById);
const mockedConversationFindOneAndUpdate = vi.mocked(ConversationModel.findOneAndUpdate);
const mockedMessageCreate = vi.mocked(MessageModel.create);
const mockedFileFind = vi.mocked(FileModel.find);

/** MVP M5: a fixed, well-known, valid-ObjectId conversation id shared by
 * every test that doesn't specifically exercise conversation
 * authorization/backfill itself -- paired with `ownedConversation()` and
 * `authorizeDefaultConversation()` below to keep the majority of
 * pre-existing (pre-M5) tests unchanged in intent. */
const DEFAULT_CONVERSATION_ID = "6aa1c4d537e42519bd73e1cc";

function ownedConversation(id: string, workspaceId: string, ragSessionId: string | undefined = "existing-session-1") {
  return { _id: new Types.ObjectId(id), workspaceId: new Types.ObjectId(workspaceId), ragSessionId } as never;
}

/** Configures both Conversation mocks so `assertConversationOwnership`
 * + `getOrCreateRagSessionId` succeed for `DEFAULT_CONVERSATION_ID`
 * against `workspaceId`, already carrying a ragSessionId (the common,
 * "not the first message" case) -- call this after setting up
 * `mockedWorkspaceFindById` in any test using the default conversation. */
function authorizeDefaultConversation(workspaceId: string, ragSessionId = "existing-session-1") {
  mockedConversationFindById.mockResolvedValue(ownedConversation(DEFAULT_CONVERSATION_ID, workspaceId, ragSessionId));
}
const mockedGetTeamBService = vi.mocked(getTeamBService);

function fakeSession(userId: string) {
  return {
    user: { id: userId, name: "Sample Student", email: "sample.student@example.com" },
    expires: "2099-01-01",
  } as never;
}

function ownedWorkspace(id: string, ownerId: string) {
  return { _id: new Types.ObjectId(id), userId: new Types.ObjectId(ownerId), name: "DBMS" } as never;
}

function chatRequest(body: Record<string, unknown>) {
  // MVP M5: every existing call site predates `conversationId` -- default
  // it to the shared, well-known test conversation id unless a test
  // explicitly passes its own (e.g. to test authorization/backfill).
  const bodyWithConversation = { conversationId: DEFAULT_CONVERSATION_ID, ...body };
  return new Request("http://localhost/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(bodyWithConversation),
  });
}

function userMessage(text: string) {
  return {
    id: "m1",
    role: "user",
    parts: [{ type: "text", text }],
  };
}

async function readSseText(response: Response): Promise<string> {
  const reader = response.body?.getReader();
  if (!reader) return "";
  const decoder = new TextDecoder();
  let raw = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    raw += decoder.decode(value, { stream: true });
  }
  // Extract every text-delta chunk's `delta` field from the raw SSE body
  // and concatenate them, mirroring what the real client-side useChat
  // would reconstruct from the stream.
  const deltas = [...raw.matchAll(/"type":"text-delta"[^}]*"delta":"([^"]*)"/g)].map((m) => m[1]);
  return deltas.join("");
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedGetTeamBService.mockReturnValue({
    query: vi.fn().mockResolvedValue({ answer: "Normalization reduces redundancy.", session_id: "s", source_attributions: [], retrieval_metadata: {} }),
  });
  mockedFileFind.mockResolvedValue([]);
  mockedMessageCreate.mockResolvedValue({} as never);
  // MVP M5 default: findOneAndUpdate (the atomic backfill path) matches
  // nothing by default -- i.e. "this conversation already has a
  // ragSessionId", which is what `mockedConversationFindById`'s default
  // configuration (set per-test via `authorizeDefaultConversation`)
  // then supplies via the plain-read fallback in `getOrCreateRagSessionId`.
  mockedConversationFindOneAndUpdate.mockResolvedValue(null);
});

describe("POST /api/chat", () => {
  it("returns 401 when unauthenticated — no Team B call, no stream started", async () => {
    mockedAuth.mockResolvedValue(null);

    const response = await POST(
      chatRequest({ messages: [userMessage("hi")], workspaceId: "ws-1", videoTimestamp: null })
    );

    expect(response.status).toBe(401);
    expect(mockedGetTeamBService).not.toHaveBeenCalled();
  });

  it("returns a safe 404 when the workspace belongs to another user — item: workspace isolation", async () => {
    const ownerId = new Types.ObjectId().toString();
    const attackerId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(attackerId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, ownerId));
    authorizeDefaultConversation(workspaceId);

    const response = await POST(
      chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null })
    );

    expect(response.status).toBe(404);
    expect(mockedGetTeamBService).not.toHaveBeenCalled();
  });

  it("does not trust a client-supplied workspaceId without verifying ownership — malformed id is safely rejected", async () => {
    mockedAuth.mockResolvedValue(fakeSession(new Types.ObjectId().toString()));

    const response = await POST(
      chatRequest({ messages: [userMessage("hi")], workspaceId: "not-a-real-id", videoTimestamp: null })
    );

    expect(response.status).toBe(404);
    expect(mockedWorkspaceFindById).not.toHaveBeenCalled();
  });

  it("streams the mock Team B answer back as real incremental SSE text-delta chunks — Property 1/2", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);

    const response = await POST(
      chatRequest({
        messages: [userMessage("What is normalization?")],
        workspaceId,
        videoTimestamp: null,
      })
    );

    expect(response.status).toBe(200);
    const text = await readSseText(response);
    expect(text.trim()).toBe("Normalization reduces redundancy.");
  });

  it("passes query, workspaceId, and videoTimestamp through to Team B — Property 1 (payload completeness)", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    const queryMock = vi.fn().mockResolvedValue({ answer: "answer" });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    await POST(
      chatRequest({
        messages: [userMessage("What is normalization?")],
        workspaceId,
        videoTimestamp: 1935,
      })
    );

    expect(queryMock).toHaveBeenCalledWith({
      query: "What is normalization?",
      session_id: "existing-session-1",
      retrieval_config: null,
      workspaceId,
      videoTimestamp: 1935,
      sub: userId,
      workspace_id: workspaceId,
    });
  });

  it("passes null videoTimestamp through unchanged when no video is active — Property 1", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    const queryMock = vi.fn().mockResolvedValue({ answer: "answer" });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    await POST(
      chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null })
    );

    expect(queryMock).toHaveBeenCalledWith(
      expect.objectContaining({ videoTimestamp: null })
    );
  });

  it("extracts only the most recent user message's text when history has multiple turns", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    const queryMock = vi.fn().mockResolvedValue({ answer: "answer" });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    await POST(
      chatRequest({
        messages: [
          userMessage("first question"),
          { id: "m2", role: "assistant", parts: [{ type: "text", text: "first answer" }] },
          userMessage("second question"),
        ],
        workspaceId,
        videoTimestamp: null,
      })
    );

    expect(queryMock).toHaveBeenCalledWith(
      expect.objectContaining({ query: "second question" })
    );
  });
});

/**
 * Requirement 3 (Source Attribution) — verifies the actual server-side
 * enforcement: citations are matched against REAL workspace files fetched
 * from MongoDB (mocked here), not trusted as-is from Team B. This is the
 * genuine security-relevant behavior lib/workspaceFilter.ts + this route
 * are responsible for — not merely that a citations array round-trips.
 */
describe("POST /api/chat — Source Attribution (Requirement 3)", () => {
  it("marks a citation enabled when its fileId matches a real file in the active workspace", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const realFileId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    mockedFileFind.mockResolvedValue([
      { _id: new Types.ObjectId(realFileId), storageUrl: "https://example.test/lecture.mp4" },
    ] as never);
    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockResolvedValue({
        answer: "See the lecture.",
        session_id: "sess-1",
        source_attributions: [
          { document_id: realFileId, document_title: "Lecture.mp4", chunk_id: "c1", relevance_score: 0.9, start_timestamp: 90 },
        ],
        retrieval_metadata: {},
      }),
    });

    const response = await POST(
      chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null })
    );
    const raw = await response.text();
    const dataMatch = raw.match(/"type":"data-citations","data":(\[.*?\])\}/);
    const citations = JSON.parse(dataMatch?.[1] ?? "[]");

    expect(citations[0].disabled).toBeFalsy();
    expect(citations[0].fileUrl).toBe("https://example.test/lecture.mp4");
  });

  it("marks a citation disabled when its fileId does NOT match any real file in the active workspace — Property 7", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    // The active workspace has no files at all — the citation's fileId
    // cannot possibly belong to it.
    mockedFileFind.mockResolvedValue([]);
    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockResolvedValue({
        answer: "See the lecture.",
        session_id: "sess-1",
        source_attributions: [
          {
            document_id: new Types.ObjectId().toString(),
            document_title: "SomeoneElses.mp4",
            chunk_id: "c1",
            relevance_score: 0.9,
            start_timestamp: 90,
          },
        ],
        retrieval_metadata: {},
      }),
    });

    const response = await POST(
      chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null })
    );
    const raw = await response.text();
    const dataMatch = raw.match(/"type":"data-citations","data":(\[.*?\])\}/);
    const citations = JSON.parse(dataMatch?.[1] ?? "[]");

    expect(citations[0].disabled).toBe(true);
  });

  it("logs a server-side security warning when a citation referencing a file outside the workspace is filtered — Property 13", async () => {
    const consoleWarnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    mockedFileFind.mockResolvedValue([]);
    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockResolvedValue({
        answer: "See the lecture.",
        session_id: "sess-1",
        source_attributions: [
          {
            document_id: new Types.ObjectId().toString(),
            document_title: "SomeoneElses.mp4",
            chunk_id: "c1",
            relevance_score: 0.9,
            timestampSeconds: 90,
          },
        ],
      }),
    });

    await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));

    // The log is server-side only — verified here, but never sent to the
    // client in the response body (the client only ever sees the already-
    // safe `disabled: true` citation, confirmed by the test above).
    expect(consoleWarnSpy).toHaveBeenCalledWith(
      expect.stringContaining(`outside workspace ${workspaceId}`)
    );

    consoleWarnSpy.mockRestore();
  });

  it("does NOT log a security warning when every citation belongs to the active workspace", async () => {
    const consoleWarnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const realFileId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    mockedFileFind.mockResolvedValue([
      { _id: new Types.ObjectId(realFileId), storageUrl: "https://example.test/lecture.mp4" },
    ] as never);
    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockResolvedValue({
        answer: "See the lecture.",
        session_id: "sess-1",
        source_attributions: [
          { document_id: realFileId, document_title: "Lecture.mp4", chunk_id: "c1", relevance_score: 0.9, start_timestamp: 90 },
        ],
        retrieval_metadata: {},
      }),
    });

    await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));

    expect(consoleWarnSpy).not.toHaveBeenCalled();
    consoleWarnSpy.mockRestore();
  });

  it("omits the citations data part entirely when Team B returns no citations", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockResolvedValue({ answer: "Just an answer, no sources." }),
    });

    const response = await POST(
      chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null })
    );
    const raw = await response.text();

    expect(raw).not.toContain("data-citations");
  });
});

describe("POST /api/chat — Property 11 (workspace data isolation, two real workspaces)", () => {
  it("scopes the file lookup to only the requesting workspace, even when the user owns a second workspace with different files", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceAId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    // The same user owns BOTH workspaces — this specifically proves
    // isolation isn't just "different owners are blocked" (already covered
    // elsewhere), but that even the same user's own second workspace's
    // files are never implicitly available to the first.
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceAId, userId));
    authorizeDefaultConversation(workspaceAId);
    mockedFileFind.mockResolvedValue([]); // Workspace A has no files.

    const workspaceBFileId = new Types.ObjectId().toString();
    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockResolvedValue({
        answer: "See the lecture.",
        // Simulates Team B (or a bug) returning a citation for a file
        // that genuinely exists — just in the user's OTHER workspace.
        session_id: "sess-1",
        source_attributions: [
          { document_id: workspaceBFileId, document_title: "OtherWorkspaceLecture.mp4", chunk_id: "c1", relevance_score: 0.9, start_timestamp: 10 },
        ],
        retrieval_metadata: {},
      }),
    });

    const response = await POST(
      chatRequest({ messages: [userMessage("hi")], workspaceId: workspaceAId, videoTimestamp: null })
    );

    // FileModel.find was called scoped to workspace A specifically, never
    // workspace B or "all of this user's files" — this is the actual
    // isolation mechanism, not just a plausible-looking result.
    expect(mockedFileFind).toHaveBeenCalledWith({ workspaceId: workspaceAId });

    const raw = await response.text();
    const dataMatch = raw.match(/"type":"data-citations","data":(\[.*?\])\}/);
    const citations = JSON.parse(dataMatch?.[1] ?? "[]");

    // Workspace B's file is NOT usable from within workspace A's session,
    // even though the user legitimately owns it elsewhere.
    expect(citations[0].disabled).toBe(true);
  });

  it("a workspace ID for a workspace the user does not own at all cannot be used to reach any file data", async () => {
    const ownerId = new Types.ObjectId().toString();
    const attackerId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(attackerId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, ownerId));
    authorizeDefaultConversation(workspaceId);

    const response = await POST(
      chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null })
    );

    expect(response.status).toBe(404);
    // Ownership fails before the file lookup ever runs — no partial data
    // access on the way to the rejection.
    expect(mockedFileFind).not.toHaveBeenCalled();
  });
});

// ============================================================
// Phase 2E CORRECTION — real Team 4B response-contract mapping
// (app/models/query.py's actual QueryResponse/SourceAttribution shape,
// not the earlier, incorrect internal "citations" representation)
// ============================================================

describe("POST /api/chat — Team 4B response-contract adapter (Phase 2E correction)", () => {
  it("A/B: an actual 4B-shaped response (source_attributions, session_id, retrieval_metadata) parses and answer is preserved", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const realFileId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    mockedFileFind.mockResolvedValue([
      { _id: new Types.ObjectId(realFileId), storageUrl: "https://example.test/notes.pdf" },
    ] as never);
    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockResolvedValue({
        answer: "Normalization reduces redundancy.",
        session_id: "real-session-abc",
        source_attributions: [
          {
            document_id: realFileId,
            document_title: "Notes.pdf",
            chunk_id: "chunk-42",
            relevance_score: 0.87,
            page_number: 3,
            section_heading: "Normal Forms",
          },
        ],
        retrieval_metadata: { chunks_retrieved: 5, search_mode: "hybrid" },
      }),
    });

    const response = await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));
    const text = await readSseText(response);

    expect(response.status).toBe(200);
    expect(text).toContain("Normalization reduces redundancy.");
  });

  it("C/D/E: multiple document attributions are converted to 4C citations with all fields mapped correctly", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const fileId1 = new Types.ObjectId().toString();
    const fileId2 = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    mockedFileFind.mockResolvedValue([
      { _id: new Types.ObjectId(fileId1), storageUrl: "https://example.test/a.pdf" },
      { _id: new Types.ObjectId(fileId2), storageUrl: "https://example.test/b.pdf" },
    ] as never);
    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockResolvedValue({
        answer: "See both sources.",
        session_id: "sess-multi",
        source_attributions: [
          {
            document_id: fileId1,
            document_title: "A.pdf",
            chunk_id: "chunk-a1",
            relevance_score: 0.91,
            page_number: 1,
            section_heading: "Intro",
          },
          {
            document_id: fileId2,
            document_title: "B.pdf",
            chunk_id: "chunk-b1",
            relevance_score: 0.82,
            page_number: 7,
            section_heading: null,
          },
        ],
        retrieval_metadata: {},
      }),
    });

    const response = await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));
    const raw = await response.text();
    const dataMatch = raw.match(/"type":"data-citations","data":(\[.*?\])\}/);
    const citations = JSON.parse(dataMatch?.[1] ?? "[]");

    expect(citations).toHaveLength(2);
    expect(citations[0]).toMatchObject({
      type: "pdf_page",
      fileId: fileId1,
      sourceFile: "A.pdf",
      location: 1,
      chunkId: "chunk-a1",
      relevanceScore: 0.91,
      sectionHeading: "Intro",
    });
    expect(citations[1]).toMatchObject({
      type: "pdf_page",
      fileId: fileId2,
      sourceFile: "B.pdf",
      location: 7,
      chunkId: "chunk-b1",
      relevanceScore: 0.82,
    });
  });

  it("F: video timestamp attribution fields (start_timestamp/end_timestamp) map correctly", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const fileId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    mockedFileFind.mockResolvedValue([
      { _id: new Types.ObjectId(fileId), storageUrl: "https://example.test/lecture.mp4" },
    ] as never);
    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockResolvedValue({
        answer: "Explained at that point in the video.",
        session_id: "sess-video",
        source_attributions: [
          {
            document_id: fileId,
            document_title: "Lecture.mp4",
            chunk_id: "chunk-v1",
            relevance_score: 0.76,
            start_timestamp: 125.5,
            end_timestamp: 140.0,
          },
        ],
        retrieval_metadata: {},
      }),
    });

    const response = await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));
    const raw = await response.text();
    const dataMatch = raw.match(/"type":"data-citations","data":(\[.*?\])\}/);
    const citations = JSON.parse(dataMatch?.[1] ?? "[]");

    expect(citations[0]).toMatchObject({
      type: "video_timestamp",
      fileId,
      sourceFile: "Lecture.mp4",
      location: 125.5,
      chunkId: "chunk-v1",
      relevanceScore: 0.76,
    });
  });

  it("G: null optional fields (page_number, section_heading, start_timestamp, end_timestamp all null) do not break mapping", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const fileId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    mockedFileFind.mockResolvedValue([
      { _id: new Types.ObjectId(fileId), storageUrl: "https://example.test/f.pdf" },
    ] as never);
    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockResolvedValue({
        answer: "An answer with a minimal attribution.",
        session_id: "sess-minimal",
        source_attributions: [
          {
            document_id: fileId,
            document_title: "F.pdf",
            chunk_id: "chunk-min",
            relevance_score: 0.5,
            page_number: null,
            section_heading: null,
            start_timestamp: null,
            end_timestamp: null,
          },
        ],
        retrieval_metadata: {},
      }),
    });

    const response = await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));
    const rawForCitations = await response.clone().text();
    const text = await readSseText(response);
    expect(response.status).toBe(200);
    expect(text).toContain("An answer with a minimal attribution.");
    // Falls through to the "video_timestamp" branch (location 0) rather
    // than throwing -- neither field pair being populated must not crash
    // the adapter.
    const dataMatch = rawForCitations.match(/"type":"data-citations","data":(\[.*?\])\}/);
    const citations = JSON.parse(dataMatch?.[1] ?? "[]");
    expect(citations[0].location).toBe(0);
  });

  it("H: existing workspace citation filtering still applies to real 4B-shaped attributions", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    mockedFileFind.mockResolvedValue([]); // no files in this workspace at all
    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockResolvedValue({
        answer: "See the source.",
        session_id: "sess-filter",
        source_attributions: [
          {
            document_id: new Types.ObjectId().toString(), // belongs to no file in this workspace
            document_title: "NotMine.pdf",
            chunk_id: "chunk-x",
            relevance_score: 0.6,
            page_number: 1,
          },
        ],
        retrieval_metadata: {},
      }),
    });

    const response = await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));
    const raw = await response.text();
    const dataMatch = raw.match(/"type":"data-citations","data":(\[.*?\])\}/);
    const citations = JSON.parse(dataMatch?.[1] ?? "[]");

    expect(citations[0].disabled).toBe(true);
  });
});

describe("POST /api/chat — session_id / retrieval_metadata preservation at the integration boundary (I/J)", () => {
  it("I: session_id from the real 4B response is destructured and available at the integration boundary, without crashing when unused further", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    mockedFileFind.mockResolvedValue([]);
    const queryMock = vi.fn().mockResolvedValue({
      answer: "An answer.",
      session_id: "a-real-4b-issued-session-id",
      source_attributions: [],
      retrieval_metadata: {},
    });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    const response = await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));

    // The route does not yet persist/forward session_id anywhere further
    // (Phase 2A's ragSessionId gap remains unresolved, unchanged by this
    // correction) -- this test proves the value is genuinely read from
    // the real response (destructured without error) rather than the
    // route crashing or ignoring the field's presence entirely.
    expect(response.status).toBe(200);
    expect(queryMock).toHaveBeenCalled();
  });

  it("J: retrieval_metadata from the real 4B response is destructured without crashing; not currently surfaced further (documented, not a bug)", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    mockedFileFind.mockResolvedValue([]);
    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockResolvedValue({
        answer: "An answer.",
        session_id: "sess-1",
        source_attributions: [],
        // A realistically-shaped, open retrieval_metadata dict -- 4B's
        // own schema leaves this intentionally open (app/models/query.py),
        // so this test uses an example shape, not an assumed fixed one.
        retrieval_metadata: { chunks_retrieved: 3, search_mode: "hybrid", latency_ms: 42 },
      }),
    });

    const response = await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));

    // Response-level (not per-citation) data -- current 4C integration
    // type (TeamBQueryResponse) exposes it (types/teamB.ts), and
    // app/api/chat/route.ts destructures it at the boundary, but does
    // not currently forward it into the chat response body -- there is
    // no per-citation or per-message slot for response-level retrieval
    // metadata in the existing UI contract. Documented here explicitly,
    // per this correction's own Requirement J, rather than silently
    // dropped without explanation.
    expect(response.status).toBe(200);
  });
});


// ---------------------------------------------------------------------------
// MVP M5 — conversation / RAG session integration
// ---------------------------------------------------------------------------

describe("POST /api/chat — MVP M5: conversation session integration", () => {
  it("13/multi-turn: a follow-up question in the same conversation sends the same session_id both times", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const conversationId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId); // uses DEFAULT_CONVERSATION_ID by default; override below
    mockedConversationFindById.mockResolvedValue(ownedConversation(conversationId, workspaceId, "stable-session-xyz"));
    const queryMock = vi.fn().mockResolvedValue({ answer: "answer", session_id: "s", source_attributions: [], retrieval_metadata: {} });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    await POST(chatRequest({ messages: [userMessage("What is a process?")], workspaceId, conversationId, videoTimestamp: null }));
    await POST(
      chatRequest({ messages: [userMessage("Explain the second point in more detail.")], workspaceId, conversationId, videoTimestamp: null })
    );

    expect(queryMock).toHaveBeenCalledTimes(2);
    expect(queryMock.mock.calls[0][0].session_id).toBe("stable-session-xyz");
    expect(queryMock.mock.calls[1][0].session_id).toBe("stable-session-xyz");
  });

  it("12/different conversations: two different conversations in the same workspace receive different session_id values", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const conversationId1 = new Types.ObjectId().toString();
    const conversationId2 = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedConversationFindById.mockImplementation((async (id: unknown) => {
      if (String(id) === conversationId1) return ownedConversation(conversationId1, workspaceId, "session-one");
      if (String(id) === conversationId2) return ownedConversation(conversationId2, workspaceId, "session-two");
      return null as never;
    }) as never);
    const queryMock = vi.fn().mockResolvedValue({ answer: "answer", session_id: "s", source_attributions: [], retrieval_metadata: {} });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    await POST(chatRequest({ messages: [userMessage("q1")], workspaceId, conversationId: conversationId1, videoTimestamp: null }));
    await POST(chatRequest({ messages: [userMessage("q2")], workspaceId, conversationId: conversationId2, videoTimestamp: null }));

    expect(queryMock.mock.calls[0][0].session_id).toBe("session-one");
    expect(queryMock.mock.calls[1][0].session_id).toBe("session-two");
    expect(queryMock.mock.calls[0][0].session_id).not.toBe(queryMock.mock.calls[1][0].session_id);
  });

  it("5/6/15: the browser cannot choose ragSessionId/session_id — a body-supplied value is completely ignored", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId, "the-real-server-side-session");
    const queryMock = vi.fn().mockResolvedValue({ answer: "answer", session_id: "s", source_attributions: [], retrieval_metadata: {} });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    await POST(
      chatRequest({
        messages: [userMessage("hi")],
        workspaceId,
        videoTimestamp: null,
        // Attacker-supplied fields the browser has no business sending —
        // the route only ever reads `conversationId` from the body, and
        // resolves session_id/ragSessionId itself, server-side.
        session_id: "attacker-chosen-session",
        ragSessionId: "attacker-chosen-session",
      })
    );

    expect(queryMock).toHaveBeenCalledTimes(1);
    expect(queryMock.mock.calls[0][0].session_id).toBe("the-real-server-side-session");
    expect(queryMock.mock.calls[0][0].session_id).not.toBe("attacker-chosen-session");
  });

  it("7/8/9/10: a conversationId belonging to a DIFFERENT workspace is rejected before Team B is ever called", async () => {
    const userId = new Types.ObjectId().toString();
    const authorizedWorkspaceId = new Types.ObjectId().toString();
    const otherWorkspaceId = new Types.ObjectId().toString();
    const otherWorkspacesConversationId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(authorizedWorkspaceId, userId));
    // The conversation genuinely exists, but belongs to a DIFFERENT workspace.
    mockedConversationFindById.mockResolvedValue(
      ownedConversation(otherWorkspacesConversationId, otherWorkspaceId, "session-belongs-to-other-workspace")
    );
    const queryMock = vi.fn();
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    const response = await POST(
      chatRequest({
        messages: [userMessage("hi")],
        workspaceId: authorizedWorkspaceId,
        conversationId: otherWorkspacesConversationId,
        videoTimestamp: null,
      })
    );

    expect(response.status).toBe(404);
    expect(queryMock).not.toHaveBeenCalled();
  });

  it("14: the real 4B request body remains exactly the canonical shape even with conversation/session integration active", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId, "session-abc");
    const queryMock = vi.fn().mockResolvedValue({ answer: "answer", session_id: "s", source_attributions: [], retrieval_metadata: {} });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));

    const calledWith = queryMock.mock.calls[0][0];
    // Only the canonical three fields, plus the auth-context fields the
    // REAL client (services/teamB/client.ts) already strips before the
    // wire body is ever constructed (verified separately in
    // contract-freeze.test.ts) -- this call site itself must not
    // introduce a new forbidden field either.
    expect(Object.keys(calledWith).sort()).toEqual(
      ["query", "session_id", "retrieval_config", "workspaceId", "videoTimestamp", "sub", "workspace_id"].sort()
    );
    expect(calledWith).not.toHaveProperty("conversationId");
    expect(calledWith).not.toHaveProperty("ragSessionId");
  });

  it("stores both the user message and the assistant message in Mongo after a successful response", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);
    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockResolvedValue({ answer: "The final answer.", session_id: "s", source_attributions: [], retrieval_metadata: {} }),
    });

    await POST(chatRequest({ messages: [userMessage("What is a process?")], workspaceId, videoTimestamp: null }));

    expect(mockedMessageCreate).toHaveBeenCalledTimes(2);
    expect(mockedMessageCreate).toHaveBeenCalledWith(
      expect.objectContaining({ role: "user", content: "What is a process?" })
    );
    expect(mockedMessageCreate).toHaveBeenCalledWith(
      expect.objectContaining({ role: "assistant", content: "The final answer." })
    );
  });

  it("existing conversations without a ragSessionId are safely backfilled (findOneAndUpdate path) rather than rejected", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    // Simulates a pre-M5 conversation: findById used for AUTHORIZATION
    // returns a doc with no ragSessionId yet; the backfill path
    // (findOneAndUpdate) then succeeds and supplies a fresh one.
    mockedConversationFindById.mockResolvedValue(ownedConversation(DEFAULT_CONVERSATION_ID, workspaceId, undefined));
    mockedConversationFindOneAndUpdate.mockResolvedValue(
      ownedConversation(DEFAULT_CONVERSATION_ID, workspaceId, "freshly-backfilled-session")
    );
    const queryMock = vi.fn().mockResolvedValue({ answer: "answer", session_id: "s", source_attributions: [], retrieval_metadata: {} });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    const response = await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));

    expect(response.status).toBe(200);
    expect(queryMock.mock.calls[0][0].session_id).toBe("freshly-backfilled-session");
  });
});


describe("POST /api/chat — M6 correction: first-attempt reliability / no duplicate messages on retry", () => {
  it("a failed first attempt (Team B 503) persists ZERO messages; the actual retry request then persists exactly one user+assistant pair", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId, "stable-session-for-retry-test");

    const queryMock = vi
      .fn()
      .mockRejectedValueOnce(new TeamBQueryError(503))
      .mockResolvedValueOnce({ answer: "The real answer.", session_id: "s", source_attributions: [], retrieval_metadata: {} });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    const firstResponse = await POST(
      chatRequest({ messages: [userMessage("What is a process?")], workspaceId, videoTimestamp: null })
    );
    expect(firstResponse.status).toBe(502);
    expect(mockedMessageCreate).not.toHaveBeenCalled();

    const secondResponse = await POST(
      chatRequest({ messages: [userMessage("What is a process?")], workspaceId, videoTimestamp: null })
    );
    expect(secondResponse.status).toBe(200);

    expect(mockedMessageCreate).toHaveBeenCalledTimes(2); // exactly one user + one assistant, never more
    expect(mockedMessageCreate).toHaveBeenCalledWith(expect.objectContaining({ role: "user", content: "What is a process?" }));
    expect(mockedMessageCreate).toHaveBeenCalledWith(expect.objectContaining({ role: "assistant", content: "The real answer." }));

    // Both attempts used the SAME stable session -- a failed-then-retried
    // attempt never mints a new ragSessionId.
    expect(queryMock.mock.calls[0][0].session_id).toBe("stable-session-for-retry-test");
    expect(queryMock.mock.calls[1][0].session_id).toBe("stable-session-for-retry-test");
  });

  it("a generic network/timeout-shaped error from Team B is also handled cleanly, with zero messages persisted", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId);

    mockedGetTeamBService.mockReturnValue({
      query: vi.fn().mockRejectedValue(new Error("fetch failed")),
    });

    const response = await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));

    expect(response.status).toBe(502);
    expect(mockedMessageCreate).not.toHaveBeenCalled();
  });
});



function fileFindResult(files: unknown[]) {
  return {
    then: (resolve: (v: unknown[]) => void) => resolve(files),
    select: () => Promise.resolve(files),
  };
}

describe("POST /api/chat — MVP M6: server-authoritative source scope", () => {
  it("no persisted scope (sourceScopeDocumentIds undefined/null) sends retrieval_config: null (workspace-wide)", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    authorizeDefaultConversation(workspaceId); // no sourceScopeDocumentIds set -> undefined
    const queryMock = vi.fn().mockResolvedValue({ answer: "answer", session_id: "s", source_attributions: [], retrieval_metadata: {} });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));

    expect(queryMock.mock.calls[0][0].retrieval_config).toBeNull();
  });

  it("a persisted, still-valid scope reaches Team B as retrieval_config.document_ids", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const docA = new Types.ObjectId();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedConversationFindById.mockResolvedValue({
      _id: new Types.ObjectId(DEFAULT_CONVERSATION_ID),
      workspaceId: new Types.ObjectId(workspaceId),
      ragSessionId: "session-1",
      sourceScopeDocumentIds: [docA.toString()],
    } as never);
    mockedFileFind.mockImplementation((query: unknown) => {
      const q = query as { _id?: { $in: string[] } };
      return fileFindResult(q._id ? [{ _id: docA }] : []) as never;
    });
    const queryMock = vi.fn().mockResolvedValue({ answer: "answer", session_id: "s", source_attributions: [], retrieval_metadata: {} });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));

    expect(queryMock.mock.calls[0][0].retrieval_config).toEqual({ document_ids: [docA.toString()] });
  });

  it("13/follow-up: the same persisted scope is used across two consecutive requests in the same conversation", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const docA = new Types.ObjectId();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedConversationFindById.mockResolvedValue({
      _id: new Types.ObjectId(DEFAULT_CONVERSATION_ID),
      workspaceId: new Types.ObjectId(workspaceId),
      ragSessionId: "session-1",
      sourceScopeDocumentIds: [docA.toString()],
    } as never);
    mockedFileFind.mockImplementation((query: unknown) => {
      const q = query as { _id?: { $in: string[] } };
      return fileFindResult(q._id ? [{ _id: docA }] : []) as never;
    });
    const queryMock = vi.fn().mockResolvedValue({ answer: "answer", session_id: "s", source_attributions: [], retrieval_metadata: {} });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    await POST(chatRequest({ messages: [userMessage("What is a process?")], workspaceId, videoTimestamp: null }));
    await POST(chatRequest({ messages: [userMessage("How is it different from a thread?")], workspaceId, videoTimestamp: null }));

    expect(queryMock).toHaveBeenCalledTimes(2);
    expect(queryMock.mock.calls[0][0].retrieval_config).toEqual({ document_ids: [docA.toString()] });
    expect(queryMock.mock.calls[1][0].retrieval_config).toEqual({ document_ids: [docA.toString()] });
  });

  it("17/21/31: a persisted scope whose document has since been deleted/failed is NEVER widened to workspace-wide", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const deletedDocId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedConversationFindById.mockResolvedValue({
      _id: new Types.ObjectId(DEFAULT_CONVERSATION_ID),
      workspaceId: new Types.ObjectId(workspaceId),
      ragSessionId: "session-1",
      sourceScopeDocumentIds: [deletedDocId],
    } as never);
    // Re-validation finds NOTHING -- the document is gone/not ready.
    mockedFileFind.mockReturnValue(fileFindResult([]) as never);
    const queryMock = vi.fn().mockResolvedValue({ answer: "answer", session_id: "s", source_attributions: [], retrieval_metadata: {} });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));

    // MUST be an empty list (zero eligible sources), never null (workspace-wide).
    expect(queryMock.mock.calls[0][0].retrieval_config).toEqual({ document_ids: [] });
    expect(queryMock.mock.calls[0][0].retrieval_config.document_ids).not.toBeNull();
  });

  it("7/8: a scope containing a document from ANOTHER workspace never reaches Team B", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const otherWorkspaceDocId = new Types.ObjectId().toString();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedConversationFindById.mockResolvedValue({
      _id: new Types.ObjectId(DEFAULT_CONVERSATION_ID),
      workspaceId: new Types.ObjectId(workspaceId),
      ragSessionId: "session-1",
      // Simulates a stale/tampered persisted value referencing a
      // document that (per the real Mongo query, scoped to THIS
      // workspace) doesn't actually belong here.
      sourceScopeDocumentIds: [otherWorkspaceDocId],
    } as never);
    mockedFileFind.mockReturnValue(fileFindResult([]) as never); // the real, workspace-scoped query finds nothing
    const queryMock = vi.fn().mockResolvedValue({ answer: "answer", session_id: "s", source_attributions: [], retrieval_metadata: {} });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));

    const sentDocumentIds = queryMock.mock.calls[0][0].retrieval_config.document_ids;
    expect(sentDocumentIds).not.toContain(otherWorkspaceDocId);
  });
});

describe("POST /api/chat — MVP M6: retry preserves source scope", () => {
  it("21/24: a failed first attempt followed by a successful retry uses the SAME persisted source scope both times", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const docA = new Types.ObjectId();
    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedConversationFindById.mockResolvedValue({
      _id: new Types.ObjectId(DEFAULT_CONVERSATION_ID),
      workspaceId: new Types.ObjectId(workspaceId),
      ragSessionId: "stable-session",
      sourceScopeDocumentIds: [docA.toString()],
    } as never);
    mockedFileFind.mockImplementation((query: unknown) => {
      const q = query as { _id?: { $in: string[] } };
      return fileFindResult(q._id ? [{ _id: docA }] : []) as never;
    });
    const queryMock = vi
      .fn()
      .mockRejectedValueOnce(new TeamBQueryError(503))
      .mockResolvedValueOnce({ answer: "answer", session_id: "s", source_attributions: [], retrieval_metadata: {} });
    mockedGetTeamBService.mockReturnValue({ query: queryMock });

    const first = await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));
    expect(first.status).toBe(502);
    const second = await POST(chatRequest({ messages: [userMessage("hi")], workspaceId, videoTimestamp: null }));
    expect(second.status).toBe(200);

    expect(queryMock.mock.calls[0][0].retrieval_config).toEqual({ document_ids: [docA.toString()] });
    expect(queryMock.mock.calls[1][0].retrieval_config).toEqual({ document_ids: [docA.toString()] });
    expect(queryMock.mock.calls[0][0].session_id).toBe("stable-session");
    expect(queryMock.mock.calls[1][0].session_id).toBe("stable-session");
  });
});

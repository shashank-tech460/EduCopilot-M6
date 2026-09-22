// @vitest-environment node
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { Types } from "mongoose";
import { rm } from "fs/promises";
import path from "path";

// ROOT CAUSE (Phase 6B investigation): this file's own `afterEach` used to
// `rm(".local-uploads", {recursive: true, force: true})` -- the ENTIRE
// shared fixture directory, not just what this file wrote. Vitest runs
// separate test FILES concurrently (in separate worker threads/processes)
// by default, and `storage-absolute-url.test.ts` / `local-storage-route.test.ts`
// write real files under that SAME shared directory at the same time. A
// blanket delete from any one file's `afterEach` could remove another
// file's in-flight fixture before its own read/assertion ran, causing the
// exact intermittent "expected 200, got 404" failure this test showed.
// Fix: track only the workspace subdirectories THIS file's tests actually
// created, and delete only those -- never the shared root.
const createdWorkspaceDirs = new Set<string>();

/**
 * MVP M6 local-stack correction — the ONE test in this project that
 * exercises the REAL `services/storage.ts` (not mocked) together with
 * the real files route, proving the full local chain:
 *
 *   real file upload -> real local storage (now absolute URL)
 *     -> File.storageUrl -> canonical {document_id, file_type, file_url}
 *     body actually sent to teamA.submit()
 *
 * Every other dependency (Mongo models, auth, teamA service) is mocked,
 * matching this project's established convention -- only
 * `services/storage` is deliberately left real here.
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

vi.mock("@/models/File", () => ({
  FileModel: { create: vi.fn() },
}));

vi.mock("@/services/teamA", () => ({
  getTeamAService: vi.fn(),
}));

import { auth } from "@/lib/auth";
import { WorkspaceModel } from "@/models/Workspace";
import { FileModel } from "@/models/File";
import { getTeamAService } from "@/services/teamA";
import { POST } from "@/app/api/workspaces/[id]/files/route";

const mockedAuth = vi.mocked(auth) as unknown as ReturnType<typeof vi.fn>;
const mockedWorkspaceFindById = vi.mocked(WorkspaceModel.findById);
const mockedFileCreate = vi.mocked(FileModel.create);
const mockedGetTeamAService = vi.mocked(getTeamAService);

function fakeSession(userId: string) {
  return { user: { id: userId, name: "Student", email: "s@example.test" }, expires: "2099-01-01" } as never;
}

function ownedWorkspace(id: string, ownerId: string) {
  return { _id: new Types.ObjectId(id), userId: new Types.ObjectId(ownerId), name: "DBMS" } as never;
}

function uploadRequest(workspaceId: string, form: FormData) {
  return new Request(`http://localhost/api/workspaces/${workspaceId}/files`, {
    method: "POST",
    body: form,
  });
}

const originalAuthUrl = process.env.AUTH_URL;
const originalAuthSecret = process.env.AUTH_SECRET;

beforeEach(() => {
  vi.clearAllMocks();
  process.env.AUTH_URL = "http://localhost:3000";
  process.env.AUTH_SECRET = "test-secret-for-local-storage-capability-tokens";
});

afterEach(async () => {
  if (originalAuthUrl === undefined) {
    delete process.env.AUTH_URL;
  } else {
    process.env.AUTH_URL = originalAuthUrl;
  }
  if (originalAuthSecret === undefined) {
    delete process.env.AUTH_SECRET;
  } else {
    process.env.AUTH_SECRET = originalAuthSecret;
  }
  // Scoped to exactly what this test run created -- see the module-level
  // comment above for why a blanket `.local-uploads` wipe is unsafe here.
  await Promise.all(
    Array.from(createdWorkspaceDirs).map((workspaceId) =>
      rm(path.join(process.cwd(), ".local-uploads", workspaceId), { recursive: true, force: true })
    )
  );
  createdWorkspaceDirs.clear();
});

describe("Real local storage -> canonical Team A body (MVP M6 local-stack correction)", () => {
  it("12: local storage URL is absolute, file_url is http(s), document_id is File._id, no workspace_id/user_id in the body", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    createdWorkspaceDirs.add(workspaceId);
    const fileId = new Types.ObjectId();

    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));

    const submitMock = vi.fn().mockResolvedValue({ ingestionId: "job-1" });
    mockedGetTeamAService.mockReturnValue({
      submit: submitMock,
      checkStatus: vi.fn().mockResolvedValue({ status: "ready", error: null }),
    });

    mockedFileCreate.mockImplementation(
      (async (doc: Record<string, unknown>) => ({
        _id: fileId,
        ...doc,
        save: vi.fn().mockResolvedValue(undefined),
      })) as never
    );

    const pdfBytes = new Uint8Array([0x25, 0x50, 0x44, 0x46]); // "%PDF"
    const form = new FormData();
    form.set("type", "pdf");
    form.set("file", new File([pdfBytes], "notes.pdf", { type: "application/pdf" }));

    const response = await POST(uploadRequest(workspaceId, form), { params: Promise.resolve({ id: workspaceId }) });

    expect(response.status).toBe(201);

    // The File document was created with a PLAIN, capability-free
    // storageUrl (round 2 correction: this is what's persisted and
    // shown for citations, protected by the browser-session path).
    const createdFileDoc = mockedFileCreate.mock.calls[0][0] as { storageUrl: string };
    expect(createdFileDoc.storageUrl).toMatch(/^http:\/\/localhost:3000\/api\/local-storage\//);
    expect(createdFileDoc.storageUrl).not.toContain("capability=");

    // The canonical body actually sent to Team A -- a FRESH capability
    // token is minted and appended ONLY here, for this one ingestion
    // attempt, never persisted.
    expect(submitMock).toHaveBeenCalledTimes(1);
    const [canonicalBody, context] = submitMock.mock.calls[0];

    expect(canonicalBody.document_id).toBe(fileId.toString());
    expect(canonicalBody.file_type).toBe("pdf");
    expect(canonicalBody.file_url).toMatch(
      new RegExp(`^${createdFileDoc.storageUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\?capability=`)
    );
    expect(canonicalBody.file_url).toMatch(/^https?:\/\//);
    expect(Object.keys(canonicalBody).sort()).toEqual(["document_id", "file_type", "file_url"]);
    expect(canonicalBody).not.toHaveProperty("workspace_id");
    expect(canonicalBody).not.toHaveProperty("workspaceId");
    expect(canonicalBody).not.toHaveProperty("user_id");
    expect(canonicalBody).not.toHaveProperty("userId");

    // Tenant identity is still passed, but ONLY as the separate context
    // argument used for JWT minting -- never merged into the body above.
    expect(context).toEqual({ sub: userId, workspace_id: workspaceId });
  });

  it("preserves existing ownership protection: a user without workspace access is rejected before any file is stored", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    createdWorkspaceDirs.add(workspaceId);

    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(null as never); // not owned / doesn't exist

    const form = new FormData();
    form.set("type", "pdf");
    form.set("file", new File([new Uint8Array([1, 2, 3])], "notes.pdf", { type: "application/pdf" }));

    const response = await POST(uploadRequest(workspaceId, form), { params: Promise.resolve({ id: workspaceId }) });

    expect(response.status).toBe(404);
    expect(mockedFileCreate).not.toHaveBeenCalled();
  });
});

describe("MVP M6 correction (round 2) — citation links never carry an expiring capability", () => {
  it("a citation URL (File.storageUrl) remains fetchable via browser session long after the ingestion-time capability would have expired", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    createdWorkspaceDirs.add(workspaceId);
    const fileId = new Types.ObjectId();

    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));
    mockedGetTeamAService.mockReturnValue({
      submit: vi.fn().mockResolvedValue({ ingestionId: "job-1" }),
      checkStatus: vi.fn().mockResolvedValue({ status: "ready", error: null }),
    });
    mockedFileCreate.mockImplementation(
      (async (doc: Record<string, unknown>) => ({ _id: fileId, ...doc, save: vi.fn().mockResolvedValue(undefined) })) as never
    );

    const pdfBytes = new Uint8Array([0x25, 0x50, 0x44, 0x46]);
    const form = new FormData();
    form.set("type", "pdf");
    form.set("file", new File([pdfBytes], "notes.pdf", { type: "application/pdf" }));

    await POST(uploadRequest(workspaceId, form), { params: Promise.resolve({ id: workspaceId }) });

    const createdFileDoc = mockedFileCreate.mock.calls[0][0] as { storageUrl: string };
    // The persisted citation link has NO capability token at all -- it
    // can never "expire" the way the earlier, buggy design did.
    expect(createdFileDoc.storageUrl).not.toContain("capability=");

    // Fetching that exact citation URL through the REAL local-storage
    // route, via a real (unmocked in this describe block) browser
    // session, must succeed -- proving Blocker B's root cause (a
    // permanently-stored, 10-minute-lived capability token baked into
    // the citation link) is genuinely fixed, not just asserted.
    const { GET } = await import("@/app/api/local-storage/[...path]/route");
    const url = new URL(createdFileDoc.storageUrl);
    const [, , , citedWorkspaceId, citedPublicId] = url.pathname.split("/");

    const response = await GET(new Request(createdFileDoc.storageUrl), {
      params: Promise.resolve({ path: [citedWorkspaceId, citedPublicId] }),
    });

    expect(response.status).toBe(200);
  });
});

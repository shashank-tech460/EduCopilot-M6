// @vitest-environment node
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { Types } from "mongoose";
import { mkdir, writeFile, rm } from "fs/promises";
import path from "path";

/**
 * MVP M6 local-storage retrieval correction — tests the REAL
 * `app/api/local-storage/[...path]/route.ts` GET handler directly (an
 * actual HTTP handler invocation, Requirement 22), proving:
 *
 *   18. the URL is fetchable via the capability token, with NO browser
 *       Auth.js session at all (`auth()` mocked to return `null`,
 *       simulating exactly what Team 4A's server-to-server resolver
 *       actually has -- nothing);
 *   19. a different/invalid/mismatched-resource capability is rejected;
 *   20. a browser session still cannot cross workspace boundaries
 *       (the ORIGINAL protection, completely unchanged);
 *   14. path traversal is still prevented on BOTH authorization paths.
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

import { auth } from "@/lib/auth";
import { WorkspaceModel } from "@/models/Workspace";
import { GET } from "@/app/api/local-storage/[...path]/route";
import { mintLocalStorageCapabilityToken } from "@/lib/localStorageCapability";

const mockedAuth = vi.mocked(auth) as unknown as ReturnType<typeof vi.fn>;
const mockedWorkspaceFindById = vi.mocked(WorkspaceModel.findById);

const LOCAL_STORAGE_ROOT = path.join(process.cwd(), ".local-uploads");
const originalAuthSecret = process.env.AUTH_SECRET;

function fakeSession(userId: string) {
  return { user: { id: userId, name: "Student", email: "s@example.test" }, expires: "2099-01-01" } as never;
}

function ownedWorkspace(id: string, ownerId: string) {
  return { _id: new Types.ObjectId(id), userId: new Types.ObjectId(ownerId), name: "DBMS" } as never;
}

async function writeRealLocalFile(workspaceId: string, publicId: string, contents: string) {
  const dir = path.join(LOCAL_STORAGE_ROOT, workspaceId);
  await mkdir(dir, { recursive: true });
  await writeFile(path.join(dir, publicId), contents);
}

function requestFor(workspaceId: string, publicId: string, capability?: string) {
  const query = capability ? `?capability=${encodeURIComponent(capability)}` : "";
  return new Request(`http://localhost/api/local-storage/${workspaceId}/${encodeURIComponent(publicId)}${query}`);
}

function paramsFor(workspaceId: string, publicId: string) {
  return { params: Promise.resolve({ path: [workspaceId, publicId] }) };
}

beforeEach(() => {
  vi.clearAllMocks();
  process.env.AUTH_SECRET = "test-secret-for-local-storage-capability-tokens";
});

afterEach(async () => {
  if (originalAuthSecret === undefined) {
    delete process.env.AUTH_SECRET;
  } else {
    process.env.AUTH_SECRET = originalAuthSecret;
  }
  await rm(LOCAL_STORAGE_ROOT, { recursive: true, force: true });
});

describe("GET /api/local-storage/[...path] — MVP M6 retrieval correction", () => {
  it("18: a valid capability token authorizes the request with NO browser session at all", async () => {
    const workspaceId = new Types.ObjectId().toString();
    const publicId = "abc-notes.pdf";
    await writeRealLocalFile(workspaceId, publicId, "pdf-bytes");

    mockedAuth.mockResolvedValue(null);

    const token = await mintLocalStorageCapabilityToken(workspaceId, publicId);
    const response = await GET(requestFor(workspaceId, publicId, token), paramsFor(workspaceId, publicId));

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("pdf-bytes");
  });

  it("19a: a capability token minted for a DIFFERENT publicId is rejected", async () => {
    const workspaceId = new Types.ObjectId().toString();
    const publicId = "real-file.pdf";
    await writeRealLocalFile(workspaceId, publicId, "pdf-bytes");
    mockedAuth.mockResolvedValue(null);

    const wrongToken = await mintLocalStorageCapabilityToken(workspaceId, "different-file.pdf");
    const response = await GET(requestFor(workspaceId, publicId, wrongToken), paramsFor(workspaceId, publicId));

    expect(response.status).toBe(404);
  });

  it("19b: a capability token minted for a DIFFERENT workspaceId is rejected", async () => {
    const workspaceId = new Types.ObjectId().toString();
    const otherWorkspaceId = new Types.ObjectId().toString();
    const publicId = "real-file.pdf";
    await writeRealLocalFile(workspaceId, publicId, "pdf-bytes");
    mockedAuth.mockResolvedValue(null);

    const wrongToken = await mintLocalStorageCapabilityToken(otherWorkspaceId, publicId);
    const response = await GET(requestFor(workspaceId, publicId, wrongToken), paramsFor(workspaceId, publicId));

    expect(response.status).toBe(404);
  });

  it("19c: a garbage/malformed capability token is rejected, never falls through to succeed", async () => {
    const workspaceId = new Types.ObjectId().toString();
    const publicId = "real-file.pdf";
    await writeRealLocalFile(workspaceId, publicId, "pdf-bytes");
    mockedAuth.mockResolvedValue(null);

    const response = await GET(
      requestFor(workspaceId, publicId, "not-a-real-token"),
      paramsFor(workspaceId, publicId)
    );

    expect(response.status).toBe(404);
  });

  it("19d: an EXPIRED capability token is rejected", async () => {
    const { SignJWT } = await import("jose");
    const workspaceId = new Types.ObjectId().toString();
    const publicId = "real-file.pdf";
    await writeRealLocalFile(workspaceId, publicId, "pdf-bytes");
    mockedAuth.mockResolvedValue(null);

    const expiredToken = await new SignJWT({ workspaceId, publicId })
      .setProtectedHeader({ alg: "HS256" })
      .setIssuedAt(Math.floor(Date.now() / 1000) - 1000)
      .setIssuer("edu-copilot-team-c-local-storage")
      .setAudience("local-storage-capability")
      .setExpirationTime(Math.floor(Date.now() / 1000) - 500)
      .sign(new TextEncoder().encode(process.env.AUTH_SECRET!));

    const response = await GET(requestFor(workspaceId, publicId, expiredToken), paramsFor(workspaceId, publicId));

    expect(response.status).toBe(404);
  });

  it("20: without a capability token, a browser session still cannot cross workspace boundaries (unchanged protection)", async () => {
    const userId = new Types.ObjectId().toString();
    const otherWorkspaceId = new Types.ObjectId().toString();
    const publicId = "real-file.pdf";
    await writeRealLocalFile(otherWorkspaceId, publicId, "someone-elses-bytes");

    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(null as never);

    const response = await GET(requestFor(otherWorkspaceId, publicId), paramsFor(otherWorkspaceId, publicId));

    expect(response.status).toBe(404);
  });

  it("20b: without a capability token, an authenticated owner of the CORRECT workspace can still read the file (unchanged)", async () => {
    const userId = new Types.ObjectId().toString();
    const workspaceId = new Types.ObjectId().toString();
    const publicId = "real-file.pdf";
    await writeRealLocalFile(workspaceId, publicId, "my-own-bytes");

    mockedAuth.mockResolvedValue(fakeSession(userId));
    mockedWorkspaceFindById.mockResolvedValue(ownedWorkspace(workspaceId, userId));

    const response = await GET(requestFor(workspaceId, publicId), paramsFor(workspaceId, publicId));

    expect(response.status).toBe(200);
    expect(await response.text()).toBe("my-own-bytes");
  });

  it("without a capability token and without a session, the request is rejected (unchanged 401)", async () => {
    const workspaceId = new Types.ObjectId().toString();
    const publicId = "real-file.pdf";
    await writeRealLocalFile(workspaceId, publicId, "bytes");
    mockedAuth.mockResolvedValue(null);

    const response = await GET(requestFor(workspaceId, publicId), paramsFor(workspaceId, publicId));

    expect(response.status).toBe(401);
  });

  it("14: path traversal is still prevented even with a valid capability token", async () => {
    const workspaceId = new Types.ObjectId().toString();
    const traversalPublicId = "../../etc/passwd";
    mockedAuth.mockResolvedValue(null);

    const token = await mintLocalStorageCapabilityToken(workspaceId, traversalPublicId);
    const response = await GET(
      requestFor(workspaceId, encodeURIComponent(traversalPublicId), token),
      paramsFor(workspaceId, encodeURIComponent(traversalPublicId))
    );

    expect(response.status).toBe(404);
  });
});

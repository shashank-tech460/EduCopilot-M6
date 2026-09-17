import { readFile } from "fs/promises";
import { NextResponse } from "next/server";

import { auth } from "@/lib/auth";
import { connectToDatabase } from "@/lib/mongodb";
import { assertOwnership, OwnershipError } from "@/lib/ownership";
import { verifyLocalStorageCapabilityToken } from "@/lib/localStorageCapability";
import { resolveLocalStoragePath } from "@/services/storage";

/**
 * Serves files written by the local development storage mock
 * (services/storage.ts). Not used at all once a real STORAGE_PROVIDER is
 * configured — a real provider serves its own URLs directly.
 *
 * Path shape: /api/local-storage/<workspaceId>/<publicId>
 *
 * TWO independent ways to authorize a request, checked in this order:
 *
 * 1. MVP M6 correction: a `?capability=<token>` query parameter --
 *    a short-lived token minted by services/storage.ts at upload time,
 *    scoped to exactly this (workspaceId, publicId) pair (see
 *    lib/localStorageCapability.ts). This is what lets Team 4A's
 *    server-to-server Phase 2C-R resolver retrieve the bytes -- it has
 *    no browser session to present, and the canonical /v1/ingest
 *    contract supplies it with only the URL itself, so the URL must be
 *    self-authorizing. A present-but-invalid/expired/mismatched-resource
 *    token is REJECTED outright (falls through to 404, exactly like any
 *    other authorization failure below) -- it is never silently ignored
 *    in favor of a session check that was never going to succeed for a
 *    non-browser caller anyway.
 *
 * 2. The ORIGINAL, unchanged mechanism: the requester must be an
 *    authenticated browser session that owns the workspace the file
 *    lives under (exactly as before this correction, in every way --
 *    same `auth()` call, same `assertOwnership()` call, same error
 *    shapes). Without this, anyone with a guessed/leaked local-storage
 *    URL (that lacks a valid capability token) could read another
 *    student's uploaded material directly.
 *
 * Either path, once authorized, is subject to the SAME, unchanged
 * `resolveLocalStoragePath()` traversal check before any byte is read.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path: segments } = await params;
  const [workspaceId, publicId] = segments;

  if (!workspaceId || !publicId) {
    return NextResponse.json({ error: "Not found." }, { status: 404 });
  }

  const decodedPublicId = decodeURIComponent(publicId);
  const capabilityToken = new URL(request.url).searchParams.get("capability");

  let authorized = false;

  if (capabilityToken) {
    authorized = await verifyLocalStorageCapabilityToken(capabilityToken, {
      workspaceId,
      publicId: decodedPublicId,
    });
    // A capability token was SUPPLIED but is invalid/expired/scoped to a
    // different resource -- this is a rejection, not a silent fallthrough
    // to the browser-session path (which a non-browser caller like Team
    // 4A could never satisfy anyway).
    if (!authorized) {
      return NextResponse.json({ error: "Not found." }, { status: 404 });
    }
  } else {
    const session = await auth();

    if (!session?.user?.id) {
      return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
    }

    await connectToDatabase();

    try {
      await assertOwnership(workspaceId, session.user.id);
      authorized = true;
    } catch (error) {
      if (error instanceof OwnershipError) {
        return NextResponse.json({ error: "Not found." }, { status: 404 });
      }
      throw error;
    }
  }

  const resolvedPath = resolveLocalStoragePath(workspaceId, decodedPublicId);

  if (!resolvedPath) {
    // publicId resolved outside this workspace's directory (path traversal
    // attempt) — same safe 404 as any other "not found/not yours" case.
    return NextResponse.json({ error: "Not found." }, { status: 404 });
  }

  try {
    const buffer = await readFile(resolvedPath);
    return new NextResponse(new Uint8Array(buffer));
  } catch {
    return NextResponse.json({ error: "Not found." }, { status: 404 });
  }
}

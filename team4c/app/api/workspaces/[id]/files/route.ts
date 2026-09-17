import { NextResponse } from "next/server";
import type { HydratedDocument } from "mongoose";

import { auth } from "@/lib/auth";
import { connectToDatabase } from "@/lib/mongodb";
import { assertOwnership, OwnershipError } from "@/lib/ownership";
import { FileModel, type File as FileDoc } from "@/models/File";
import { validateUploadedFile, validateYoutubeUrl } from "@/lib/validation";
import { storeFile, referenceYoutubeUrl, mintLocalStorageRetrievalUrl } from "@/services/storage";
import { getTeamAService } from "@/services/teamA";
import { toCanonicalFileType } from "@/types/teamA";

function serializeFile(file: HydratedDocument<FileDoc>) {
  return {
    id: file._id.toString(),
    originalName: file.originalName,
    type: file.type,
    status: file.status,
    processingError: file.processingError ?? null,
    storageUrl: file.storageUrl,
    createdAt: file.createdAt,
    sizeBytes: file.sizeBytes ?? null,
  };
}

/**
 * Drives a newly-created file through the Team A hand-off
 * (docs/decisions.md §6/§9): submit → store ingestionId → check status →
 * store the result. Uses whichever implementation getTeamAService()
 * currently resolves to (mock by default) — this function has no idea, and
 * doesn't need to, whether it's talking to the mock or a real service.
 *
 * Runs synchronously within the upload request — the REAL canonical
 * `/v1/ingest` (Phase 2C) is itself synchronous (it runs the full Phase 1
 * pipeline to completion before responding), so this was never actually
 * the async/background concern an earlier phase's comment anticipated.
 *
 * CANONICAL CONTRACT (Phase 2A freeze, unchanged): `document_id` is this
 * File's own `_id`. `workspace_id`/`user_id` are NEVER part of the wire
 * body sent to `/v1/ingest` — Phase 2D wires them in as the SEPARATE
 * `context` argument to `teamA.submit()` (`userId`, `file.workspaceId`),
 * which the real client (services/teamA/client.ts) uses only to mint the
 * Phase 2B internal service JWT, never to populate the request body.
 * `userId` here is the authenticated session's own id; `file.workspaceId`
 * was already confirmed by this route's own `assertOwnership()` call
 * before this function is ever invoked — this function relies on its
 * caller having already done so (Requirement 5).
 */
async function handOffToTeamA(file: HydratedDocument<FileDoc>, userId: string): Promise<HydratedDocument<FileDoc>> {
  const teamA = getTeamAService();

  try {
    // MVP M6 correction (round 2): the URL sent to Team 4A is minted
    // fresh here, for THIS ingestion attempt only -- see
    // services/storage.ts's `mintLocalStorageRetrievalUrl` for why this
    // must be separate from `file.storageUrl` itself (which is
    // permanent, capability-free, and browser-session-protected for
    // citation clicks).
    const fileUrlForIngestion = await mintLocalStorageRetrievalUrl({
      storageUrl: file.storageUrl,
      storageProvider: file.storageProvider,
      publicId: file.publicId,
      workspaceId: file.workspaceId.toString(),
    });

    const { ingestionId } = await teamA.submit(
      {
        document_id: file._id.toString(),
        file_type: toCanonicalFileType(file.type),
        file_url: fileUrlForIngestion,
      },
      // Phase 2D: server-verified identity, supplied ONLY here (never as
      // part of the canonical request body above) -- `userId` is the
      // authenticated session's own id, and `file.workspaceId` was
      // already confirmed to belong to that user by this route's own
      // `assertOwnership()` call before `handOffToTeamA` is ever invoked.
      { sub: userId, workspace_id: file.workspaceId.toString() }
    );

    file.ingestionId = ingestionId;
    file.status = "processing";
    await file.save();

    const statusResult = await teamA.checkStatus(ingestionId);
    file.status = statusResult.status;
    file.processingError = statusResult.error;
    await file.save();
  } catch (error) {
    file.status = "failed";
    file.processingError = error instanceof Error ? error.message : "Unknown ingestion error.";
    await file.save();
  }

  return file;
}

/**
 * GET /api/workspaces/[id]/files — materials belonging to this workspace,
 * only if the requester owns it.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await auth();

  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  const { id: workspaceId } = await params;

  await connectToDatabase();

  try {
    await assertOwnership(workspaceId, session.user.id);
  } catch (error) {
    if (error instanceof OwnershipError) {
      return NextResponse.json({ error: "Not found." }, { status: 404 });
    }
    throw error;
  }

  const files = await FileModel.find({ workspaceId }).sort({ createdAt: -1 });

  return NextResponse.json(files.map(serializeFile));
}

/**
 * POST /api/workspaces/[id]/files — upload a PDF/MP4, or register a
 * YouTube URL, into this workspace.
 *
 * Accepts multipart/form-data with a `type` field ("pdf" | "video" |
 * "youtube_url") plus either a `file` field (pdf/video) or a `youtubeUrl`
 * field. A single uniform request shape for all three material types keeps
 * the client and this route simple, rather than branching on Content-Type.
 */
export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await auth();

  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  const { id: workspaceId } = await params;

  await connectToDatabase();

  try {
    await assertOwnership(workspaceId, session.user.id);
  } catch (error) {
    if (error instanceof OwnershipError) {
      return NextResponse.json({ error: "Not found." }, { status: 404 });
    }
    throw error;
  }

  const formData = await request.formData().catch(() => null);
  if (!formData) {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }

  const materialType = formData.get("type");

  if (materialType === "youtube_url") {
    const url = formData.get("youtubeUrl");
    const { valid, error } = validateYoutubeUrl(url);

    if (!valid || typeof url !== "string") {
      return NextResponse.json({ error }, { status: 400 });
    }

    const stored = referenceYoutubeUrl(url.trim());
    const file = await FileModel.create({
      workspaceId,
      userId: session.user.id,
      originalName: url.trim(),
      type: "youtube_url",
      storageUrl: stored.storageUrl,
      storageProvider: stored.storageProvider,
      status: "uploading",
    });

    const finished = await handOffToTeamA(file, session.user.id);
    return NextResponse.json(serializeFile(finished), { status: 201 });
  }

  if (materialType === "pdf" || materialType === "video") {
    const uploaded = formData.get("file");
    const { valid, error } = validateUploadedFile(uploaded, materialType);

    if (!valid || !(uploaded instanceof globalThis.File)) {
      return NextResponse.json({ error }, { status: 400 });
    }

    const stored = await storeFile(uploaded, workspaceId);
    const file = await FileModel.create({
      workspaceId,
      userId: session.user.id,
      originalName: uploaded.name,
      type: materialType,
      storageUrl: stored.storageUrl,
      storageProvider: stored.storageProvider,
      publicId: stored.publicId,
      status: "uploading",
      sizeBytes: uploaded.size,
    });

    const finished = await handOffToTeamA(file, session.user.id);
    return NextResponse.json(serializeFile(finished), { status: 201 });
  }

  return NextResponse.json({ error: "Unsupported material type." }, { status: 400 });
}

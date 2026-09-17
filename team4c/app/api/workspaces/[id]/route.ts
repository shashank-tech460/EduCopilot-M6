import { NextResponse } from "next/server";

import { auth } from "@/lib/auth";
import { connectToDatabase } from "@/lib/mongodb";
import { assertOwnership, OwnershipError } from "@/lib/ownership";
import { WorkspaceModel } from "@/models/Workspace";
import { FileModel } from "@/models/File";
import { ConversationModel } from "@/models/Conversation";
import { MessageModel } from "@/models/Message";
import { deleteStoredFile } from "@/services/storage";

/**
 * GET /api/workspaces/[id] — fetch a single workspace, but only if the
 * authenticated user owns it. Added for Step 2 (Workspace Initialization):
 * a client-side hook using React Query needs a real endpoint to call,
 * mirroring the exact ownership pattern already used by DELETE below
 * rather than introducing a second way to check ownership.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await auth();

  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  const { id } = await params;

  await connectToDatabase();

  let workspace;
  try {
    workspace = await assertOwnership(id, session.user.id);
  } catch (error) {
    if (error instanceof OwnershipError) {
      return NextResponse.json({ error: "Not found." }, { status: 404 });
    }
    throw error;
  }

  return NextResponse.json({
    id: workspace._id.toString(),
    name: workspace.name,
    createdAt: workspace.createdAt,
  });
}

/**
 * DELETE /api/workspaces/[id] — delete a workspace, but only if the
 * authenticated user owns it. Reuses the existing assertOwnership() helper
 * (lib/ownership.ts) rather than re-implementing the check here.
 *
 * Cascade-deletes everything that belongs to this workspace, in an order
 * that respects the actual reference direction (docs/decisions.md §3):
 *   1. Stored file bytes for every File (best-effort — deleteStoredFile()
 *      already swallows "already gone" errors, so a partially-cleaned-up
 *      workspace from a previous failed attempt can't block this).
 *   2. File documents.
 *   3. Message documents (they reference conversationId, not workspaceId
 *      directly, so they're looked up via this workspace's conversation
 *      IDs first).
 *   4. Conversation documents.
 *   5. The Workspace document itself, last — if anything above throws,
 *      the workspace stays visible rather than disappearing while orphaned
 *      children remain, which would make the leftover data unreachable
 *      through any UI (no route lists files/conversations without a
 *      workspace to scope the ownership check to).
 */
export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const session = await auth();

  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  const { id } = await params;

  await connectToDatabase();

  try {
    await assertOwnership(id, session.user.id);
  } catch (error) {
    if (error instanceof OwnershipError) {
      // Same indistinguishable 404 as everywhere else ownership is checked
      // — a workspace that exists but isn't yours must look identical to
      // one that doesn't exist at all.
      return NextResponse.json({ error: "Not found." }, { status: 404 });
    }
    throw error;
  }

  const files = await FileModel.find({ workspaceId: id });
  await Promise.all(
    files.map((file) =>
      deleteStoredFile(file.storageProvider ?? undefined, file.publicId ?? undefined, id)
    )
  );
  await FileModel.deleteMany({ workspaceId: id });

  const conversations = await ConversationModel.find({ workspaceId: id }, { _id: 1 });
  const conversationIds = conversations.map((conversation) => conversation._id);
  if (conversationIds.length > 0) {
    await MessageModel.deleteMany({ conversationId: { $in: conversationIds } });
  }
  await ConversationModel.deleteMany({ workspaceId: id });

  await WorkspaceModel.findByIdAndDelete(id);

  return NextResponse.json({ success: true });
}

import { NextResponse } from "next/server";
import { Types } from "mongoose";

import { auth } from "@/lib/auth";
import { connectToDatabase } from "@/lib/mongodb";
import { assertOwnership, OwnershipError } from "@/lib/ownership";
import { FileModel } from "@/models/File";
import { deleteStoredFile } from "@/services/storage";

/**
 * DELETE /api/workspaces/[id]/files/[fileId]
 *
 * Two ownership checks, deliberately: first that the *workspace* belongs to
 * the requester (via the existing assertOwnership() helper — not
 * duplicated), then that the *file* actually belongs to *that* workspace
 * (not just any workspace the ID happens to resolve to). Both failure modes
 * return the same safe 404, consistent with every other ownership check in
 * this project.
 */
export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ id: string; fileId: string }> }
) {
  const session = await auth();

  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  const { id: workspaceId, fileId } = await params;

  await connectToDatabase();

  try {
    await assertOwnership(workspaceId, session.user.id);
  } catch (error) {
    if (error instanceof OwnershipError) {
      return NextResponse.json({ error: "Not found." }, { status: 404 });
    }
    throw error;
  }

  if (!Types.ObjectId.isValid(fileId)) {
    return NextResponse.json({ error: "Not found." }, { status: 404 });
  }

  const file = await FileModel.findById(fileId);

  if (!file || file.workspaceId.toString() !== workspaceId) {
    return NextResponse.json({ error: "Not found." }, { status: 404 });
  }

  await deleteStoredFile(file.storageProvider ?? undefined, file.publicId ?? undefined, workspaceId);
  await FileModel.findByIdAndDelete(fileId);

  return NextResponse.json({ success: true });
}

import { Types } from "mongoose";
import { NextResponse } from "next/server";

import { auth } from "@/lib/auth";
import { connectToDatabase } from "@/lib/mongodb";
import { assertOwnership, OwnershipError } from "@/lib/ownership";
import { validateAndNormalizeSourceScope } from "@/lib/sourceScope";
import { ConversationModel } from "@/models/Conversation";

const MAX_SELECTED_SOURCES = 100; // matches Team 4B's own RetrievalConfig.document_ids bound exactly

/**
 * PATCH /api/conversations/[id]/scope — MVP M6.
 *
 * Request body: `{ "document_ids": string[] | null }`.
 * `null` clears the scope (workspace-wide). A non-null list is
 * validated and normalized (deduplicated, filtered to only
 * workspace-owned, `ready` Files) before being persisted -- the browser
 * is never trusted to have already done this correctly.
 *
 * Authorization: resolves the Conversation's OWN workspace first, then
 * verifies the authenticated user owns THAT workspace (the same
 * security property `assertConversationOwnership` establishes, just
 * without requiring the caller to already know/supply a workspaceId --
 * this route's URL only ever carries `conversationId`).
 *
 * Returns the ACTUAL persisted scope (which may be a strict subset of
 * what was requested, if some requested IDs were invalid/unauthorized/
 * not ready) -- so the UI can immediately reflect what really took
 * effect, without a second round-trip.
 */
/**
 * GET /api/conversations/[id]/scope — MVP M6 correction.
 *
 * Returns the CURRENT authoritative `sourceScopeDocumentIds` for an
 * authorized conversation -- the read-side counterpart to the existing
 * `PATCH` handler below. This is what lets the client hydrate its
 * source-scope UI state when a conversation is established/reopened
 * (hooks/useSourceScope.ts), rather than only ever learning about scope
 * changes it itself just made via PATCH.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  const { id: conversationId } = await params;
  await connectToDatabase();

  if (!Types.ObjectId.isValid(conversationId)) {
    return NextResponse.json({ error: "Not found." }, { status: 404 });
  }

  const conversation = await ConversationModel.findById(conversationId);
  if (!conversation) {
    return NextResponse.json({ error: "Not found." }, { status: 404 });
  }

  try {
    await assertOwnership(conversation.workspaceId.toString(), session.user.id);
  } catch (error) {
    if (error instanceof OwnershipError) {
      return NextResponse.json({ error: "Not found." }, { status: 404 });
    }
    throw error;
  }

  return NextResponse.json({ document_ids: conversation.sourceScopeDocumentIds ?? null });
}

export async function PATCH(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  const { id: conversationId } = await params;
  const body = await request.json().catch(() => null);
  if (!body || !("document_ids" in body)) {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }

  const { document_ids: requestedDocumentIds } = body as { document_ids: unknown };
  if (requestedDocumentIds !== null && !Array.isArray(requestedDocumentIds)) {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }
  if (Array.isArray(requestedDocumentIds) && requestedDocumentIds.length > MAX_SELECTED_SOURCES) {
    return NextResponse.json(
      { error: `A maximum of ${MAX_SELECTED_SOURCES} sources may be selected at once.` },
      { status: 400 }
    );
  }

  await connectToDatabase();

  if (!Types.ObjectId.isValid(conversationId)) {
    return NextResponse.json({ error: "Not found." }, { status: 404 });
  }

  const conversation = await ConversationModel.findById(conversationId);
  if (!conversation) {
    return NextResponse.json({ error: "Not found." }, { status: 404 });
  }

  const workspaceId = conversation.workspaceId.toString();

  try {
    await assertOwnership(workspaceId, session.user.id);
  } catch (error) {
    if (error instanceof OwnershipError) {
      return NextResponse.json({ error: "Not found." }, { status: 404 });
    }
    throw error;
  }

  const normalizedScope =
    requestedDocumentIds === null
      ? null
      : await validateAndNormalizeSourceScope(requestedDocumentIds as string[], workspaceId);

  await ConversationModel.findByIdAndUpdate(conversationId, { sourceScopeDocumentIds: normalizedScope });

  return NextResponse.json({ document_ids: normalizedScope });
}

import { NextResponse } from "next/server";
import type { HydratedDocument } from "mongoose";

import { auth } from "@/lib/auth";
import { connectToDatabase } from "@/lib/mongodb";
import { assertOwnership, OwnershipError } from "@/lib/ownership";
import { generateRagSessionId } from "@/lib/ragSession";
import { ConversationModel, type Conversation as ConversationDoc } from "@/models/Conversation";

/**
 * POST /api/workspaces/[id]/conversations — MVP M5.
 *
 * Creates a new, durable Team 4C Conversation with a fresh,
 * server-generated `ragSessionId` already attached at creation time.
 * There is no race condition to guard against HERE specifically (a
 * single `ConversationModel.create()` call either succeeds once or
 * fails; there is nothing else to race with for a brand-new document) —
 * the race this task is concerned with (a legacy conversation being
 * lazily backfilled by two concurrent requests) is handled separately,
 * in `lib/ragSession.ts`'s `getOrCreateRagSessionId()`, used by the
 * chat route for EXISTING conversations.
 *
 * `title` is accepted from the request body as a simple, user-supplied
 * label (matching the existing `Conversation.title` field's own
 * documented purpose — "auto-generated from the first message... and
 * user-editable") — it carries no security significance and is never
 * used to derive `ragSessionId` (Requirement: "Do not derive
 * ragSessionId from... conversation title").
 */
function serializeConversation(conversation: HydratedDocument<ConversationDoc>) {
  return {
    id: conversation._id.toString(),
    workspaceId: conversation.workspaceId.toString(),
    title: conversation.title,
  };
}

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
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

  const body = await request.json().catch(() => ({}));
  const title = typeof body?.title === "string" && body.title.trim() ? body.title.trim() : "New conversation";

  const conversation = await ConversationModel.create({
    workspaceId,
    title,
    // Server-generated ONLY — never read from `body`, never supplied by
    // the browser. A brand-new document has no prior ragSessionId to
    // race against, so a plain, direct assignment at creation time is
    // sufficient here (unlike the lazy-backfill path).
    ragSessionId: generateRagSessionId(),
  });

  return NextResponse.json(serializeConversation(conversation), { status: 201 });
}

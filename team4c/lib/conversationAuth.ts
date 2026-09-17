import { Types } from "mongoose";

import { assertOwnership, OwnershipError } from "@/lib/ownership";
import { ConversationModel, type Conversation } from "@/models/Conversation";

/**
 * MVP M5 — verifies that `conversationId` both exists and belongs to a
 * workspace `userId` owns, per the exact chain this task requires:
 *
 *     browser -> conversationId
 *             -> 4C authenticates user            (caller's job)
 *             -> 4C verifies workspace ownership   (assertOwnership, below)
 *             -> 4C verifies the conversation belongs to that workspace (here)
 *
 * Reuses `OwnershipError` (lib/ownership.ts) rather than inventing a
 * second error type -- "workspace not yours", "conversation doesn't
 * exist", and "conversation belongs to a different workspace" are all
 * reported identically for the same reason `assertOwnership` already
 * documents: distinguishing them would make the ID space probeable.
 *
 * On success, returns the Conversation document -- the caller (the chat
 * route) needs it next for `getOrCreateRagSessionId()`.
 */
export async function assertConversationOwnership(
  conversationId: string,
  workspaceId: string,
  userId: string
): Promise<Conversation> {
  // Verifies the WORKSPACE first -- a conversationId is meaningless
  // without an authorized workspace context to check it against, and
  // this also means an invalid/unauthorized workspaceId is rejected
  // before ever touching the Conversation collection at all.
  await assertOwnership(workspaceId, userId);

  if (!Types.ObjectId.isValid(conversationId)) {
    throw new OwnershipError();
  }

  const conversation = await ConversationModel.findById(conversationId);

  if (!conversation || conversation.workspaceId.toString() !== workspaceId) {
    // Deliberately the SAME error/message for "doesn't exist" and
    // "exists but belongs to a different workspace" -- exactly
    // `assertOwnership`'s own established reasoning, applied here too.
    throw new OwnershipError();
  }

  return conversation;
}

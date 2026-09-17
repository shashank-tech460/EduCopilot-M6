import { randomUUID } from "crypto";
import { Types } from "mongoose";

import { ConversationModel } from "@/models/Conversation";

/**
 * MVP M5 — the Team 4B RAG session identity for a Team 4C Conversation.
 *
 * Generation: a cryptographically secure random UUID v4 (Node's built-in
 * `crypto.randomUUID()`, already used elsewhere in this codebase for the
 * same reason — see app/api/chat/route.ts's message-id generation) —
 * never derived from userId, workspaceId, conversation title, a
 * timestamp, or any predictable counter. 4B places no format
 * requirement on `session_id` (app/models/query.py: `session_id: str |
 * None`, no pattern/length constraint) — a UUID v4 string is simply a
 * convenient, already-proven-safe choice, not something 4B requires.
 */
export function generateRagSessionId(): string {
  return randomUUID();
}

/**
 * Atomically returns the given Conversation's stable `ragSessionId`,
 * generating and persisting one on first use if it doesn't exist yet
 * (covers BOTH a genuinely new Conversation and a pre-M5 Conversation
 * being backfilled lazily) — race-safe under concurrent callers for the
 * SAME conversationId (the documented "browser opens conversation +
 * immediately sends first question" scenario, and concurrent legacy-
 * conversation backfill).
 *
 * MECHANISM: a single, atomic, conditional `findOneAndUpdate` —
 * `{_id: conversationId, ragSessionId: {$exists: false}}` — only ever
 * WRITES a ragSessionId when the document does not already have one.
 * MongoDB guarantees this compare-and-set is atomic at the single-
 * document level: if two requests race for the same conversationId,
 * at most ONE of them can match this filter and perform the write: the
 * other's conditional update matches zero documents (because the first
 * writer's update already made `ragSessionId` exist), so it falls
 * through to the plain re-read below and gets back the FIRST writer's
 * value — never generating or persisting a second, competing
 * ragSessionId for the same Conversation. This is a genuine MongoDB-
 * level atomicity guarantee (a single `findOneAndUpdate` on one
 * document), not an application-level lock or a "check then write" race.
 *
 * Returns `null` if the conversation does not exist at all (the caller
 * is expected to have already authorized the conversation's existence
 * via `lib/conversationAuth.ts` before ever calling this).
 */
export async function getOrCreateRagSessionId(conversationId: string): Promise<string | null> {
  if (!Types.ObjectId.isValid(conversationId)) {
    return null;
  }

  const candidate = generateRagSessionId();

  const updated = await ConversationModel.findOneAndUpdate(
    { _id: conversationId, ragSessionId: { $exists: false } },
    { $set: { ragSessionId: candidate } },
    { new: true }
  );

  if (updated) {
    // This request won the race (or no race occurred) -- its own
    // freshly-generated candidate is now the persisted value.
    return updated.ragSessionId ?? null;
  }

  // Either the conversation already had a ragSessionId (the common
  // case for every request after the first), or the conversation
  // doesn't exist at all -- a single plain read distinguishes the two
  // and returns the CURRENT authoritative value either way. The
  // `candidate` generated above is simply discarded in this branch --
  // it is only ever written to Mongo inside the conditional update, so
  // a discarded candidate here has no observable side effect anywhere.
  const existing = await ConversationModel.findById(conversationId);
  return existing?.ragSessionId ?? null;
}

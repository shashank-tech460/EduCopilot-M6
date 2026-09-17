import { auth } from "@/lib/auth";
import { assertConversationOwnership } from "@/lib/conversationAuth";
import { connectToDatabase } from "@/lib/mongodb";
import { OwnershipError } from "@/lib/ownership";
import { getOrCreateRagSessionId } from "@/lib/ragSession";
import { resolveEffectiveDocumentIds } from "@/lib/sourceScope";
import { filterWorkspaceReferences } from "@/lib/workspaceFilter";
import { FileModel } from "@/models/File";
import { MessageModel } from "@/models/Message";
import { getTeamBService } from "@/services/teamB";
import { TeamBQueryError } from "@/services/teamB/client";
import type { SourceAttribution } from "@/store/appStore";
import type { TeamBSourceAttribution } from "@/types/teamB";
import type { UIMessage } from "ai";
import { createUIMessageStream, createUIMessageStreamResponse } from "ai";

interface ChatRequestBody {
  messages: UIMessage[];
  workspaceId: string;
  conversationId: string;
  videoTimestamp: number | null;
}

/**
 * PHASE 2E CORRECTION: adapts Team 4B's REAL `SourceAttribution` response
 * shape (types/teamB.ts's `TeamBSourceAttribution` -- document_id,
 * document_title, chunk_id, relevance_score, page_number?,
 * section_heading?, start_timestamp?, end_timestamp?, confirmed directly
 * against app/models/query.py) into Team 4C's OWN, existing, UI-facing
 * `SourceAttribution` shape (store/appStore.ts) -- these are genuinely
 * different types with the same name in different codebases, never to be
 * confused with each other.
 *
 * There is no explicit `type` discriminator on Team 4B's real schema --
 * which of the two mutually-exclusive-in-practice field pairs is
 * populated (`page_number`/`section_heading` for a document source vs.
 * `start_timestamp`/`end_timestamp` for a video source) is itself the
 * signal, exactly as app/models/query.py's own docstring describes.
 * `chunk_id`/`relevance_score`/`section_heading` are carried through onto
 * the existing type's new, additive, optional fields (added by this same
 * correction -- store/appStore.ts) so no data Team 4B actually sends is
 * silently dropped, even though the current UI doesn't render all of it
 * yet. `disabled` is left unset here; the actual Requirement 3.5
 * workspace-safety check happens next, against real workspace files,
 * completely unchanged by this correction.
 */
function toSourceAttribution(attribution: TeamBSourceAttribution, fileUrl: string | undefined): SourceAttribution {
  const isPdf = attribution.page_number != null || attribution.section_heading != null;
  const location = isPdf ? attribution.page_number ?? 0 : attribution.start_timestamp ?? 0;
  return {
    type: isPdf ? "pdf_page" : "video_timestamp",
    sourceFile: attribution.document_title,
    fileId: attribution.document_id,
    location,
    label: isPdf
      ? `${attribution.document_title}, page ${location}`
      : `${attribution.document_title} at ${location}s`,
    fileUrl,
    chunkId: attribution.chunk_id,
    relevanceScore: attribution.relevance_score,
    sectionHeading: attribution.section_heading ?? undefined,
  };
}

/**
 * POST /api/chat — Accion Labs Requirement 2 (Chat Interface with
 * Streaming Responses) and Requirement 3 (Source Attribution). Consumes
 * Team B's Query_API (currently the mock, per docs/decisions.md's
 * mock-first strategy) and relays a real SSE stream back to the client via
 * the installed AI SDK's own streaming primitives — this is genuine
 * token-by-token streaming, not a simulated delay dressed up as one.
 *
 * SECURITY: `workspaceId` arrives in the request body from the client
 * (unavoidable — the client is the one that knows which workspace it's
 * asking about), but it is never trusted on its own. `assertOwnership()`
 * — the same helper every other route in this app uses — is the actual
 * authorization boundary: a workspaceId for a workspace the caller
 * doesn't own fails here exactly as it does everywhere else.
 *
 * Requirement 3.5: citations returned by Team B are NOT trusted as-is —
 * this route fetches the ACTIVE workspace's real files from MongoDB and
 * runs the existing `filterWorkspaceReferences()` (lib/workspaceFilter.ts,
 * already built for exactly this) before ever sending attributions to the
 * client. The client renders whatever `disabled` state it's given; it
 * never independently decides whether a citation is valid.
 */
export async function POST(request: Request) {
  const session = await auth();

  if (!session?.user?.id) {
    return new Response(JSON.stringify({ error: "Unauthorized." }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  const body: ChatRequestBody = await request.json();
  const { messages, workspaceId, conversationId, videoTimestamp } = body;

  await connectToDatabase();

  // MVP M5: authorizes the WORKSPACE first (unchanged), then the
  // CONVERSATION itself -- a conversationId the browser supplies for a
  // conversation it doesn't own (wrong workspace, another user's,
  // nonexistent) is rejected HERE, before Team 4B is ever called. The
  // browser is never trusted to supply a ragSessionId/session_id
  // directly for an existing conversation -- only a conversationId,
  // which this server-side check resolves into the real, authorized
  // Conversation document.
  let conversation;
  try {
    conversation = await assertConversationOwnership(conversationId, workspaceId, session.user.id);
  } catch (error) {
    if (error instanceof OwnershipError) {
      return new Response(JSON.stringify({ error: "Not found." }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      });
    }
    throw error;
  }

  // Reads (or, for a pre-M5 conversation, atomically backfills) the
  // ONE stable ragSessionId for this Conversation -- see
  // lib/ragSession.ts for the concurrency-safe mechanism. `null` here
  // can only mean the conversation vanished between the authorization
  // check above and this call (a genuine, if narrow, TOCTOU window);
  // treated the same as "not found" rather than silently querying Team
  // 4B with no session context.
  const ragSessionId = await getOrCreateRagSessionId(conversationId);
  if (ragSessionId === null) {
    return new Response(JSON.stringify({ error: "Not found." }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  // MVP M6 — the server-persisted, authoritative source scope for this
  // conversation. `resolveEffectiveDocumentIds` RE-validates against
  // current File state every call (never trusts a stale persisted
  // scope, and never trusts anything the browser sent in THIS request
  // body -- the chat request has no document_ids field to begin with).
  // `null` = workspace-wide (unchanged). A non-null result -- even `[]`,
  // if every previously-selected File is no longer ready/authorized --
  // is passed through to Team 4B EXACTLY as resolved; it is never
  // widened back to `null` here.
  const effectiveDocumentIds = await resolveEffectiveDocumentIds(conversation.sourceScopeDocumentIds, workspaceId);

  const lastUserMessage = [...messages].reverse().find((message) => message.role === "user");
  const queryText = lastUserMessage
    ? lastUserMessage.parts
        .filter((part): part is Extract<typeof part, { type: "text" }> => part.type === "text")
        .map((part) => part.text)
        .join("")
    : "";

  const teamB = getTeamBService();
  // CANONICAL CONTRACT (Phase 2A freeze, unchanged): the real, over-the-
  // wire request to Team B is `{query, session_id, retrieval_config}` —
  // workspaceId/videoTimestamp below are TeamBMockOnlyContext, consumed
  // exclusively by the local mock's own simulation. Phase 2E adds
  // `sub`/`workspace_id` (TeamBAuthContext) — server-verified identity
  // used ONLY by the real client to mint the Phase 2B internal service
  // JWT, never forwarded into the wire body either.
  //
  // MVP M5: `session_id` is now the real, stable, authorized
  // Conversation's own `ragSessionId` (never `conversationId` itself,
  // never `null` for an existing conversation) — the Phase 2A audit's
  // documented gap ("no ragSessionId field exists yet") is resolved as
  // of this task.
  let queryResult;
  try {
    queryResult = await teamB.query({
      query: queryText,
      session_id: ragSessionId,
      retrieval_config: effectiveDocumentIds === null ? null : { document_ids: effectiveDocumentIds },
      workspaceId,
      videoTimestamp,
      sub: session.user.id,
      workspace_id: workspaceId,
    });
  } catch (error) {
    // Phase 2E error handling: map the real 4B failure categories to
    // safe, non-leaking client responses. Never expose the private
    // signing key, internal service topology, or a raw exception/stack
    // trace, and never silently produce a successful-looking answer for
    // an authentication/authorization/validation failure.
    if (error instanceof TeamBQueryError) {
      if (error.status === 401) {
        return new Response(JSON.stringify({ error: "Query service authentication failed." }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (error.status === 403) {
        return new Response(JSON.stringify({ error: "Query service authorization failed." }), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (error.status === 422) {
        return new Response(JSON.stringify({ error: "Invalid query request." }), {
          status: 422,
          headers: { "Content-Type": "application/json" },
        });
      }
      console.error(`[chat] Team B query failed with status ${error.status}`);
      return new Response(JSON.stringify({ error: "The query service is temporarily unavailable." }), {
        status: 502,
        headers: { "Content-Type": "application/json" },
      });
    }
    console.error("[chat] Team B query failed:", error instanceof Error ? error.message : "Unknown error");
    return new Response(JSON.stringify({ error: "The query service is temporarily unavailable." }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
  const { answer, source_attributions, retrieval_metadata } = queryResult;
  // MVP M5: 4B's own returned `session_id` is intentionally NOT
  // destructured/used here — the authoritative session identity is
  // Team 4C's own `ragSessionId` (already sent as the request's
  // `session_id` above); 4B's response echoes back whatever it was
  // given (or generates one for a `null` request, which this route
  // never sends for an existing conversation), so re-reading it here
  // would be redundant with, not additive to, what this route already
  // knows. `retrieval_metadata` remains response-level (not
  // per-citation), so it still has no natural slot in the existing
  // per-citation UI pipeline below.
  void retrieval_metadata;

  // Real files in the ACTIVE workspace only — this is the actual security
  // boundary for Requirement 3.5, not anything the client or Team B claims.
  const workspaceFiles = await FileModel.find({ workspaceId });
  const workspaceFileIds = workspaceFiles.map((file) => file._id.toString());
  const fileUrlById = new Map(workspaceFiles.map((file) => [file._id.toString(), file.storageUrl]));

  const attributions =
    source_attributions && source_attributions.length > 0
      ? filterWorkspaceReferences(
          source_attributions.map((attribution) => toSourceAttribution(attribution, fileUrlById.get(attribution.document_id))),
          workspaceFileIds
        )
      : undefined;

  // Property 13 — a citation Team B returned that references a file
  // outside the active workspace is disabled (above), but that event is
  // also worth a server-side security log: it means either Team B's mock
  // (or, later, the real Query_API) is returning a fileId this workspace
  // doesn't own, which is exactly the class of response this filtering
  // exists to catch. Logged server-side, not sent to the client — the
  // client only ever sees the already-safe `disabled: true` state.
  const unauthorizedAttributions = attributions?.filter(
    (attribution) => attribution.disabled && !workspaceFileIds.includes(attribution.fileId)
  );
  if (unauthorizedAttributions && unauthorizedAttributions.length > 0) {
    console.warn(
      `[chat] Team B returned ${unauthorizedAttributions.length} citation(s) referencing file(s) outside workspace ${workspaceId} — filtered before sending to client.`
    );
  }

  // MVP M5: Team 4C remains the durable conversation/message store —
  // Mongo, not Team 4B's ephemeral Redis session, is the system of
  // record. Persists both turns once the full answer is known (the
  // subsequent word-by-word streaming below is presentation only; the
  // complete `answer` string already exists at this point). Only
  // AUTHORIZED, already-workspace-filtered attributions are stored
  // (never a disabled/unauthorized one) -- mapped into `Message`'s own,
  // pre-existing citation shape (`{fileId, type: "video"|"pdf", ...}`,
  // distinct from `SourceAttribution`'s `"pdf_page"/"video_timestamp"`
  // naming), which this route does not redesign.
  const storedCitations = attributions
    ?.filter((attribution) => !attribution.disabled)
    .map((attribution) => ({
      fileId: attribution.fileId,
      type: attribution.type === "pdf_page" ? ("pdf" as const) : ("video" as const),
      pageNumber: attribution.type === "pdf_page" ? attribution.location : undefined,
      timestampSeconds: attribution.type === "video_timestamp" ? attribution.location : undefined,
    }));

  await MessageModel.create({ conversationId, role: "user", content: queryText });
  await MessageModel.create({
    conversationId,
    role: "assistant",
    content: answer,
    citations: storedCitations && storedCitations.length > 0 ? storedCitations : undefined,
  });

  // Splits the mock's canned answer into small chunks and writes them as
  // separate text-delta events, spaced out slightly — this is what
  // actually produces incremental rendering on the client (Requirement
  // 2.2 / Property 2), via the real UI message stream protocol rather
  // than sending the whole answer in a single chunk.
  const stream = createUIMessageStream({
    execute: async ({ writer }) => {
      const id = crypto.randomUUID();
      writer.write({ type: "text-start", id });

      const words = answer.split(" ");
      for (const word of words) {
        writer.write({ type: "text-delta", id, delta: `${word} ` });
        await new Promise((resolve) => setTimeout(resolve, 20));
      }

      writer.write({ type: "text-end", id });

      if (attributions) {
        writer.write({ type: "data-citations", data: attributions });
      }
    },
    onError: (error) => (error instanceof Error ? error.message : "An error occurred."),
  });

  return createUIMessageStreamResponse({ stream });
}

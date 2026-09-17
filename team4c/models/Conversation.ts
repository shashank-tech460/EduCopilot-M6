import { Schema, model, models, Types, type InferSchemaType, type Model } from "mongoose";

/**
 * Fields match docs/decisions.md §4 "conversations" exactly.
 *
 * A conversation belongs to exactly one workspace (docs/decisions.md §3).
 * `title` is expected to be auto-generated from the first message once chat
 * exists (Phase 8/9) and is user-editable — Phase 3 only stores the field.
 */
const conversationSchema = new Schema(
  {
    workspaceId: {
      type: Schema.Types.ObjectId,
      ref: "Workspace",
      required: true,
      index: true,
    },
    title: {
      type: String,
      required: true,
      trim: true,
    },
    /**
     * MVP M5: the stable Team 4B RAG session identifier for this
     * Conversation -- distinct from `_id` (the durable, permanent
     * application-level conversation identity, which Team 4B never
     * sees at all). Server-generated only (lib/ragSession.ts's
     * `generateRagSessionId()`, a cryptographically random UUID v4) --
     * never supplied by the browser, and never derived from userId/
     * workspaceId/title/timestamp/a counter.
     *
     * `required: false` (not `true`): a Conversation created before
     * this field existed has no value here at all -- lazily,
     * atomically backfilled on first use by
     * `lib/ragSession.ts`'s `getOrCreateRagSessionId()`, never
     * generated eagerly for every existing document via a bulk
     * migration.
     *
     * `unique: true` + `sparse: true`: enforces that no two
     * Conversations ever share a ragSessionId once one is assigned,
     * while permitting arbitrarily many existing documents that don't
     * have the field at all yet (a plain `unique` index without
     * `sparse` would reject having more than one document with a
     * missing/null value).
     */
    ragSessionId: {
      type: String,
      required: false,
      unique: true,
      sparse: true,
    },
    /**
     * MVP M6 — persistent, server-authoritative source scope for this
     * Conversation. `document_id` (`File._id`) identity ONLY -- never
     * filename, storageUrl, or any other display value.
     *
     * `null` (the default): workspace-wide retrieval -- no explicit
     * scope. `[]` is NEVER used to mean this (it would be a dangerous,
     * silent widening); an explicit selection that has become entirely
     * invalid (e.g. every selected File was deleted) is represented as
     * an EMPTY array here on purpose, distinct from `null`, so
     * `app/api/chat/route.ts` can tell "no scope was ever set" apart
     * from "a scope was set but nothing in it is usable right now" --
     * the latter must never fall back to workspace-wide search (see
     * that route's own scope-resolution logic).
     *
     * Set only via `PATCH /api/conversations/[id]/scope`
     * (app/api/conversations/[id]/scope/route.ts), which re-validates
     * every ID against the conversation's own workspace, the
     * authenticated user's ownership, and each File's current `status`
     * before persisting anything here -- this field is never written
     * directly from an unvalidated request body anywhere else.
     */
    sourceScopeDocumentIds: {
      type: [String],
      required: false,
      default: null,
    },
  },
  {
    timestamps: true,
  }
);

export type Conversation = InferSchemaType<typeof conversationSchema> & {
  _id: Types.ObjectId;
};

export const ConversationModel: Model<Conversation> =
  models.Conversation ?? model<Conversation>("Conversation", conversationSchema);

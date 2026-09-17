import { Schema, model, models, Types, type InferSchemaType, type Model } from "mongoose";

/**
 * Fields match docs/decisions.md §4 "messages" exactly.
 *
 * `citations` mirrors the exact shape agreed in docs/api-contracts.md §B.2 /
 * §B.5: { fileId, type, timestampSeconds?, pageNumber? }. No additional
 * citation fields (e.g. a text snippet) are added here — that field is
 * explicitly marked "TO CONFIRM" in api-contracts.md, not approved yet, so
 * it does not belong in the schema until Team B's contract is finalized.
 *
 * `citations[].type` intentionally has only two values ("video" | "pdf"),
 * not three — this is a deliberate subset of the file `type` enum, not an
 * omission. A `youtube_url` file's citations use type "video", since both
 * MP4 and YouTube content seek identically via react-player. This mapping is
 * documented in docs/decisions.md §16, item 2.
 */
export const CITATION_TYPE_VALUES = ["video", "pdf"] as const;
export type CitationType = (typeof CITATION_TYPE_VALUES)[number];

export const MESSAGE_ROLE_VALUES = ["user", "assistant"] as const;
export type MessageRole = (typeof MESSAGE_ROLE_VALUES)[number];

const citationSchema = new Schema(
  {
    fileId: {
      type: Schema.Types.ObjectId,
      ref: "File",
      required: true,
    },
    type: {
      type: String,
      enum: CITATION_TYPE_VALUES,
      required: true,
    },
    timestampSeconds: {
      type: Number,
      required: false,
    },
    pageNumber: {
      type: Number,
      required: false,
    },
  },
  { _id: false }
);

const messageSchema = new Schema(
  {
    conversationId: {
      type: Schema.Types.ObjectId,
      ref: "Conversation",
      required: true,
      index: true,
    },
    role: {
      type: String,
      enum: MESSAGE_ROLE_VALUES,
      required: true,
    },
    content: {
      type: String,
      required: true,
    },
    citations: {
      type: [citationSchema],
      required: false,
      default: undefined,
    },
  },
  {
    timestamps: { createdAt: true, updatedAt: false },
  }
);

export type Message = InferSchemaType<typeof messageSchema> & {
  _id: Types.ObjectId;
};

export const MessageModel: Model<Message> =
  models.Message ?? model<Message>("Message", messageSchema);

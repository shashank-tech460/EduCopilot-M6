import { Schema, model, models, Types, type InferSchemaType, type Model } from "mongoose";

/**
 * Fields match docs/decisions.md §4 "workspaces" exactly.
 *
 * `userId` is the sole ownership reference for a workspace (docs/decisions.md
 * §3: "Every workspace has exactly one owning user"). It is indexed because
 * every "list my workspaces" query and every ownership check filters on it —
 * this is the highest-traffic query pattern for this collection.
 */
const workspaceSchema = new Schema(
  {
    userId: {
      type: Schema.Types.ObjectId,
      ref: "User",
      required: true,
      index: true,
    },
    name: {
      type: String,
      required: true,
      trim: true,
    },
  },
  {
    timestamps: true,
  }
);

export type Workspace = InferSchemaType<typeof workspaceSchema> & {
  _id: Types.ObjectId;
};

export const WorkspaceModel: Model<Workspace> =
  models.Workspace ?? model<Workspace>("Workspace", workspaceSchema);

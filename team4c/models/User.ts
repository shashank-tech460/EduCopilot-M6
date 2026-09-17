import { Schema, model, models, Types, type InferSchemaType, type Model } from "mongoose";

/**
 * Fields match docs/decisions.md §4 "users" exactly.
 *
 * `passwordHash` is required because Team C's approved auth architecture
 * (docs/decisions.md §7) uses Auth.js's Credentials provider. It is never
 * selected by default on normal queries (see `select: false`) so a stray
 * `User.find()` elsewhere in the app can't accidentally leak it — callers
 * that genuinely need it (the Credentials provider's authorize() function,
 * built in Phase 4) must explicitly opt in with `.select("+passwordHash")`.
 */
const userSchema = new Schema(
  {
    name: {
      type: String,
      required: true,
      trim: true,
    },
    email: {
      type: String,
      required: true,
      unique: true,
      lowercase: true,
      trim: true,
    },
    passwordHash: {
      type: String,
      required: true,
      select: false,
    },
  },
  {
    timestamps: { createdAt: true, updatedAt: false },
  }
);

export type User = InferSchemaType<typeof userSchema> & {
  _id: Types.ObjectId;
};

export const UserModel: Model<User> = models.User ?? model<User>("User", userSchema);

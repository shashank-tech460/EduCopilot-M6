/**
 * Development seed script.
 *
 * Creates one realistic sample record per collection, respecting every
 * required field, enum value, and ownership relationship approved in
 * docs/decisions.md. Safe to re-run — it looks up existing sample records by
 * a fixed email/name before creating new ones, so running it twice does not
 * create duplicates.
 *
 * DEV-ONLY SAMPLE CREDENTIALS (Phase 4):
 *   email:    sample.student@example.com
 *   password: DevPassword123!
 * These exist only in your local/dev database for manually testing the
 * login flow. Never reuse this password for anything real, and never seed
 * this script against a production database.
 *
 * Usage:
 *   1. cp .env.example .env.local and set a real MONGODB_URI
 *   2. npx tsx scripts/seed.ts
 */
import "dotenv/config";
import bcrypt from "bcrypt";

import { connectToDatabase } from "../lib/mongodb";
import { UserModel } from "../models/User";
import { WorkspaceModel } from "../models/Workspace";
import { FileModel } from "../models/File";
import { ConversationModel } from "../models/Conversation";
import { MessageModel } from "../models/Message";

const SAMPLE_USER_EMAIL = "sample.student@example.com";
const SAMPLE_USER_PASSWORD = "DevPassword123!";
const SALT_ROUNDS = 12;

async function seed() {
  await connectToDatabase();

  const passwordHash = await bcrypt.hash(SAMPLE_USER_PASSWORD, SALT_ROUNDS);

  // .select("+passwordHash") because the schema hides it by default — we
  // need to read it here to detect and migrate the Phase 3 placeholder.
  let user = await UserModel.findOne({ email: SAMPLE_USER_EMAIL }).select("+passwordHash");

  if (!user) {
    user = await UserModel.create({
      name: "Sample Student",
      email: SAMPLE_USER_EMAIL,
      passwordHash,
    });
    console.log(`User:         ${user._id} (${user.email}) — created with a real bcrypt hash`);
  } else if (!user.passwordHash.startsWith("$2")) {
    // Migrates a Phase 3 record still holding the old
    // "NOT_A_REAL_HASH__replace_via_Auth.js_in_Phase_4" placeholder (real
    // bcrypt hashes always start with "$2"). Re-running this script is what
    // performs the replacement the Phase 4 spec requires.
    user.passwordHash = passwordHash;
    await user.save();
    console.log(`User:         ${user._id} (${user.email}) — migrated placeholder to a real bcrypt hash`);
  } else {
    console.log(`User:         ${user._id} (${user.email}) — already has a real password hash`);
  }


  const workspace =
    (await WorkspaceModel.findOne({ userId: user._id, name: "DBMS" })) ??
    (await WorkspaceModel.create({
      userId: user._id,
      name: "DBMS",
    }));
  console.log(`Workspace:    ${workspace._id} (${workspace.name})`);

  const file =
    (await FileModel.findOne({
      workspaceId: workspace._id,
      originalName: "Lecture12-Normalization.mp4",
    })) ??
    (await FileModel.create({
      workspaceId: workspace._id,
      userId: user._id,
      originalName: "Lecture12-Normalization.mp4",
      type: "video",
      storageUrl: "https://example-object-storage.test/lecture12.mp4",
      storageProvider: "sample-provider",
      status: "ready",
      durationSeconds: 2745,
    }));
  console.log(`File:         ${file._id} (${file.originalName}, status=${file.status})`);

  const conversation =
    (await ConversationModel.findOne({
      workspaceId: workspace._id,
      title: "Normalization",
    })) ??
    (await ConversationModel.create({
      workspaceId: workspace._id,
      title: "Normalization",
    }));
  console.log(`Conversation: ${conversation._id} (${conversation.title})`);

  const existingMessages = await MessageModel.countDocuments({
    conversationId: conversation._id,
  });

  if (existingMessages === 0) {
    await MessageModel.create([
      {
        conversationId: conversation._id,
        role: "user",
        content: "What is normalization?",
      },
      {
        conversationId: conversation._id,
        role: "assistant",
        content:
          "Normalization is the process of organizing a database's tables and columns to reduce data redundancy, as explained starting around 32:15 in this lecture.",
        citations: [
          {
            fileId: file._id,
            type: "video",
            timestampSeconds: 1935,
          },
        ],
      },
    ]);
    console.log("Messages:     2 created (1 user, 1 assistant with a video citation)");
  } else {
    console.log(`Messages:     ${existingMessages} already exist, skipped`);
  }

  console.log("\nSeed complete.");
  console.log(`Sample login: ${SAMPLE_USER_EMAIL} / ${SAMPLE_USER_PASSWORD} (dev only)`);
}

seed()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error("Seed failed:", error);
    process.exit(1);
  });

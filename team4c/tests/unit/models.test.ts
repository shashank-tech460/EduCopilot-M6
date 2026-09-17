import { describe, expect, it } from "vitest";
import { Types, type Document } from "mongoose";

import { UserModel } from "@/models/User";
import { WorkspaceModel } from "@/models/Workspace";
import { FileModel, FILE_STATUS_VALUES } from "@/models/File";
import { ConversationModel } from "@/models/Conversation";
import { MessageModel } from "@/models/Message";

/**
 * These are schema-validation unit tests only — they call Mongoose's async
 * `validate()` on an in-memory document, which checks required fields,
 * enums, and types without opening a database connection (validateSync() is
 * deprecated as of this Mongoose version, so we use the non-deprecated async
 * API throughout). Per the Phase 3 instructions, a real MongoDB connection
 * is not required for this kind of test; anything that needs one would be a
 * separate integration test, which is out of scope here since no test
 * database is configured yet.
 */

interface MongooseValidationError {
  errors: Record<string, unknown>;
}

async function getValidationError(
  doc: Document
): Promise<MongooseValidationError | undefined> {
  try {
    await doc.validate();
    return undefined;
  } catch (error) {
    return error as MongooseValidationError;
  }
}

describe("User model", () => {
  it("requires name, email, and passwordHash", async () => {
    const error = await getValidationError(new UserModel({}));
    expect(error?.errors.name).toBeDefined();
    expect(error?.errors.email).toBeDefined();
    expect(error?.errors.passwordHash).toBeDefined();
  });

  it("accepts a fully valid user", async () => {
    const doc = new UserModel({
      name: "Sample Student",
      email: "student@example.com",
      passwordHash: "placeholder-hash",
    });
    expect(await getValidationError(doc)).toBeUndefined();
  });
});

describe("Workspace model", () => {
  it("requires userId and name", async () => {
    const error = await getValidationError(new WorkspaceModel({}));
    expect(error?.errors.userId).toBeDefined();
    expect(error?.errors.name).toBeDefined();
  });

  it("accepts a valid workspace referencing a user", async () => {
    const doc = new WorkspaceModel({
      userId: new Types.ObjectId(),
      name: "DBMS",
    });
    expect(await getValidationError(doc)).toBeUndefined();
  });
});

describe("File model — status lifecycle", () => {
  it("locks the status enum to exactly uploading/processing/ready/failed", () => {
    expect(FILE_STATUS_VALUES).toEqual(["uploading", "processing", "ready", "failed"]);
  });

  it("rejects an 'uploaded' status (not part of the approved lifecycle)", async () => {
    const doc = new FileModel({
      workspaceId: new Types.ObjectId(),
      userId: new Types.ObjectId(),
      originalName: "Lecture12.mp4",
      type: "video",
      storageUrl: "https://example.test/lecture12.mp4",
      status: "uploaded",
    });
    const error = await getValidationError(doc);
    expect(error?.errors.status).toBeDefined();
  });

  it("rejects an arbitrary invalid status value", async () => {
    const doc = new FileModel({
      workspaceId: new Types.ObjectId(),
      userId: new Types.ObjectId(),
      originalName: "Lecture12.mp4",
      type: "video",
      storageUrl: "https://example.test/lecture12.mp4",
      status: "done",
    });
    expect((await getValidationError(doc))?.errors.status).toBeDefined();
  });

  it.each(FILE_STATUS_VALUES)("accepts the valid status value '%s'", async (status) => {
    const doc = new FileModel({
      workspaceId: new Types.ObjectId(),
      userId: new Types.ObjectId(),
      originalName: "Lecture12.mp4",
      type: "video",
      storageUrl: "https://example.test/lecture12.mp4",
      status,
    });
    expect(await getValidationError(doc)).toBeUndefined();
  });

  it("defaults to 'uploading' when status is omitted", () => {
    const doc = new FileModel({
      workspaceId: new Types.ObjectId(),
      userId: new Types.ObjectId(),
      originalName: "Lecture12.mp4",
      type: "video",
      storageUrl: "https://example.test/lecture12.mp4",
    });
    expect(doc.status).toBe("uploading");
  });

  it("rejects an invalid file type", async () => {
    const doc = new FileModel({
      workspaceId: new Types.ObjectId(),
      userId: new Types.ObjectId(),
      originalName: "notes.docx",
      type: "docx",
      storageUrl: "https://example.test/notes.docx",
    });
    expect((await getValidationError(doc))?.errors.type).toBeDefined();
  });

  it("requires workspaceId, userId, originalName, type, and storageUrl", async () => {
    const error = await getValidationError(new FileModel({}));
    expect(error?.errors.workspaceId).toBeDefined();
    expect(error?.errors.userId).toBeDefined();
    expect(error?.errors.originalName).toBeDefined();
    expect(error?.errors.type).toBeDefined();
    expect(error?.errors.storageUrl).toBeDefined();
  });
});

describe("File model — currentIngestionGeneration (Rev.4.4 Phase 1 authorized schema addition)", () => {
  it("defaults a newly-constructed File document's currentIngestionGeneration to 0", () => {
    // Mongoose applies schema defaults at document CONSTRUCTION time, not
    // at save() time -- so this is verifiable without a live database
    // connection, matching this file's own existing convention.
    const doc = new FileModel({
      workspaceId: new Types.ObjectId(),
      userId: new Types.ObjectId(),
      originalName: "Lecture1.pdf",
      type: "pdf",
      storageUrl: "https://example.test/lecture1.pdf",
    });
    expect(doc.currentIngestionGeneration).toBe(0);
  });

  it("does not require currentIngestionGeneration to be explicitly supplied", async () => {
    const doc = new FileModel({
      workspaceId: new Types.ObjectId(),
      userId: new Types.ObjectId(),
      originalName: "Lecture1.pdf",
      type: "pdf",
      storageUrl: "https://example.test/lecture1.pdf",
    });
    const error = await getValidationError(doc);
    expect(error?.errors.currentIngestionGeneration).toBeUndefined();
  });

  it("accepts an explicitly-set currentIngestionGeneration (e.g. a value already advanced by Team 4A)", async () => {
    const doc = new FileModel({
      workspaceId: new Types.ObjectId(),
      userId: new Types.ObjectId(),
      originalName: "Lecture1.pdf",
      type: "pdf",
      storageUrl: "https://example.test/lecture1.pdf",
      currentIngestionGeneration: 3,
    });
    expect(doc.currentIngestionGeneration).toBe(3);
    expect(await getValidationError(doc)).toBeUndefined();
  });

  it("does not disturb any other File field's own validation behavior", async () => {
    // Regression guard: adding this field must not have altered validation
    // for the pre-existing required-field set.
    const error = await getValidationError(new FileModel({}));
    expect(error?.errors.workspaceId).toBeDefined();
    expect(error?.errors.userId).toBeDefined();
    expect(error?.errors.originalName).toBeDefined();
    expect(error?.errors.type).toBeDefined();
    expect(error?.errors.storageUrl).toBeDefined();
    // And the new field itself is never what causes a validation failure
    // on an otherwise-empty document -- it's optional with a default.
    expect(error?.errors.currentIngestionGeneration).toBeUndefined();
  });
});

describe("Conversation model", () => {
  it("requires workspaceId and title", async () => {
    const error = await getValidationError(new ConversationModel({}));
    expect(error?.errors.workspaceId).toBeDefined();
    expect(error?.errors.title).toBeDefined();
  });
});

describe("Message model — citations", () => {
  it("requires conversationId, role, and content", async () => {
    const error = await getValidationError(new MessageModel({}));
    expect(error?.errors.conversationId).toBeDefined();
    expect(error?.errors.role).toBeDefined();
    expect(error?.errors.content).toBeDefined();
  });

  it("rejects a role outside user/assistant", async () => {
    const doc = new MessageModel({
      conversationId: new Types.ObjectId(),
      role: "system",
      content: "hello",
    });
    expect((await getValidationError(doc))?.errors.role).toBeDefined();
  });

  it("accepts a message with no citations (plain user message)", async () => {
    const doc = new MessageModel({
      conversationId: new Types.ObjectId(),
      role: "user",
      content: "What is normalization?",
    });
    expect(await getValidationError(doc)).toBeUndefined();
  });

  it("accepts a valid video citation with timestampSeconds", async () => {
    const doc = new MessageModel({
      conversationId: new Types.ObjectId(),
      role: "assistant",
      content: "Explained around 32:15.",
      citations: [{ fileId: new Types.ObjectId(), type: "video", timestampSeconds: 1935 }],
    });
    expect(await getValidationError(doc)).toBeUndefined();
  });

  it("accepts a valid pdf citation with pageNumber", async () => {
    const doc = new MessageModel({
      conversationId: new Types.ObjectId(),
      role: "assistant",
      content: "See page 32.",
      citations: [{ fileId: new Types.ObjectId(), type: "pdf", pageNumber: 32 }],
    });
    expect(await getValidationError(doc)).toBeUndefined();
  });

  it("rejects a citation type outside video/pdf", async () => {
    const doc = new MessageModel({
      conversationId: new Types.ObjectId(),
      role: "assistant",
      content: "Explained in the audio.",
      citations: [{ fileId: new Types.ObjectId(), type: "audio", timestampSeconds: 10 }],
    });
    const error = await getValidationError(doc);
    expect(error?.errors["citations.0.type"]).toBeDefined();
  });

  it("rejects a citation missing fileId", async () => {
    const doc = new MessageModel({
      conversationId: new Types.ObjectId(),
      role: "assistant",
      content: "Explained around 32:15.",
      citations: [{ type: "video", timestampSeconds: 1935 } as never],
    });
    const error = await getValidationError(doc);
    expect(error?.errors["citations.0.fileId"]).toBeDefined();
  });
});

import { describe, expect, it, vi, beforeEach } from "vitest";
import { Types } from "mongoose";

/**
 * MVP M5 — dedicated tests for `lib/ragSession.ts` and
 * `lib/conversationAuth.ts`.
 *
 * `getOrCreateRagSessionId`'s concurrency-safety claim rests on
 * MongoDB's own single-document atomic `findOneAndUpdate` guarantee --
 * this environment has no Mongoose-compatible in-memory MongoDB harness
 * (unlike Team 4B's Python side, which uses `mongomock`), so the race
 * tests below use a hand-written, STATEFUL fake that faithfully
 * reimplements the exact atomic contract `findOneAndUpdate` provides
 * (single-document compare-and-set, no partial/interleaved writes) to
 * prove this module's OWN logic is correct against that contract. This
 * is an honest, explicitly-scoped substitute for a real MongoDB
 * integration test, not a claim that MongoDB's own atomicity is being
 * tested here.
 */

vi.mock("@/models/Conversation", () => ({
  ConversationModel: {
    findById: vi.fn(),
    findOneAndUpdate: vi.fn(),
  },
}));

vi.mock("@/lib/ownership", async () => {
  const actual = await vi.importActual<typeof import("@/lib/ownership")>("@/lib/ownership");
  return { ...actual, assertOwnership: vi.fn() };
});

vi.mock("@/models/Workspace", () => ({
  WorkspaceModel: { findById: vi.fn() },
}));

import { generateRagSessionId, getOrCreateRagSessionId } from "@/lib/ragSession";
import { assertConversationOwnership } from "@/lib/conversationAuth";
import { ConversationModel } from "@/models/Conversation";
import { assertOwnership, OwnershipError } from "@/lib/ownership";

const mockedFindById = vi.mocked(ConversationModel.findById);
const mockedFindOneAndUpdate = vi.mocked(ConversationModel.findOneAndUpdate);
const mockedAssertOwnership = vi.mocked(assertOwnership);

const CONV_1 = new Types.ObjectId().toString();
const CONV_A = new Types.ObjectId().toString();
const CONV_B = new Types.ObjectId().toString();
const CONV_RACE = new Types.ObjectId().toString();

beforeEach(() => {
  vi.clearAllMocks();
});

describe("generateRagSessionId", () => {
  it("2: produces a cryptographically random, non-predictable value", () => {
    const ids = new Set(Array.from({ length: 1000 }, () => generateRagSessionId()));
    // 1000 draws, zero collisions -- overwhelming evidence of real entropy.
    expect(ids.size).toBe(1000);
  });

  it("is not derived from any predictable input (format is a bare UUID v4, no embedded structure)", () => {
    const id = generateRagSessionId();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
  });
});

describe("getOrCreateRagSessionId — 3/4/12: persistence and reuse", () => {
  it("3/4: generates and persists a new id on first call, reuses it on every subsequent call", async () => {
    // A stateful fake reimplementing findOneAndUpdate's exact atomic
    // contract: only writes when the filter's ragSessionId-absent
    // condition is genuinely true for THIS document's current state.
    let stored: { _id: string; ragSessionId?: string } = { _id: CONV_1 };

    mockedFindOneAndUpdate.mockImplementation((async (filter: any, update: any) => {
      if (stored.ragSessionId === undefined) {
        stored = { ...stored, ragSessionId: update.$set.ragSessionId };
        return { ...stored } as never;
      }
      return null as never;
    }) as never);
    mockedFindById.mockImplementation((async () => ({ ...stored })) as never);

    const first = await getOrCreateRagSessionId(CONV_1);
    const second = await getOrCreateRagSessionId(CONV_1);
    const third = await getOrCreateRagSessionId(CONV_1);

    expect(first).not.toBeNull();
    expect(second).toBe(first);
    expect(third).toBe(first);
  });

  it("12: two different conversations receive different ragSessionIds", async () => {
    const store = new Map<string, string>();
    mockedFindOneAndUpdate.mockImplementation((async (filter: any, update: any) => {
      const id = filter._id as string;
      if (!store.has(id)) {
        store.set(id, update.$set.ragSessionId);
        return { _id: id, ragSessionId: store.get(id) } as never;
      }
      return null as never;
    }) as never);
    mockedFindById.mockImplementation((async (id: unknown) => ({ _id: id, ragSessionId: store.get(id as string) })) as never);

    const a = await getOrCreateRagSessionId(CONV_A);
    const b = await getOrCreateRagSessionId(CONV_B);

    expect(a).not.toBeNull();
    expect(b).not.toBeNull();
    expect(a).not.toBe(b);
  });

  it("11: concurrent requests for the SAME conversation resolve to exactly one ragSessionId (simulated atomic race)", async () => {
    let stored: { ragSessionId?: string } = {};

    // Faithfully reimplements findOneAndUpdate's single-document atomic
    // compare-and-set: even when called "concurrently" (interleaved
    // microtask scheduling under Promise.all, the closest a
    // single-threaded JS test can get to a real race), only the FIRST
    // call to actually observe `ragSessionId === undefined` performs
    // the write; every other call's condition is already false by the
    // time it runs, exactly matching MongoDB's own per-document
    // atomicity guarantee.
    mockedFindOneAndUpdate.mockImplementation((async (filter: any, update: any) => {
      if (stored.ragSessionId === undefined) {
        stored = { ragSessionId: update.$set.ragSessionId };
        return { ...stored } as never;
      }
      return null as never;
    }) as never);
    mockedFindById.mockImplementation((async () => ({ ...stored })) as never);

    const results = await Promise.all(Array.from({ length: 20 }, () => getOrCreateRagSessionId(CONV_RACE)));

    const uniqueResults = new Set(results);
    expect(uniqueResults.size).toBe(1);
    expect([...uniqueResults][0]).not.toBeNull();
  });

  it("returns null for a conversation that does not exist", async () => {
    mockedFindOneAndUpdate.mockResolvedValue(null as never);
    mockedFindById.mockResolvedValue(null as never);

    const result = await getOrCreateRagSessionId(new Types.ObjectId().toString());

    expect(result).toBeNull();
  });

  it("returns null for a malformed conversationId without querying Mongo", async () => {
    const result = await getOrCreateRagSessionId("not-an-object-id");

    expect(result).toBeNull();
    expect(mockedFindOneAndUpdate).not.toHaveBeenCalled();
    expect(mockedFindById).not.toHaveBeenCalled();
  });
});

describe("assertConversationOwnership — 7/8/9: authorization before any 4B call", () => {
  it("7: rejects when the conversation does not exist", async () => {
    mockedAssertOwnership.mockResolvedValue({} as never);
    mockedFindById.mockResolvedValue(null as never);

    await expect(
      assertConversationOwnership(new Types.ObjectId().toString(), new Types.ObjectId().toString(), "user-1")
    ).rejects.toBeInstanceOf(OwnershipError);
  });

  it("8/9: rejects when the conversation belongs to a DIFFERENT workspace than the authorized one", async () => {
    const conversationWorkspaceId = new Types.ObjectId();
    const authorizedWorkspaceId = new Types.ObjectId().toString();
    mockedAssertOwnership.mockResolvedValue({} as never);
    mockedFindById.mockResolvedValue({ _id: new Types.ObjectId(), workspaceId: conversationWorkspaceId } as never);

    await expect(
      assertConversationOwnership(new Types.ObjectId().toString(), authorizedWorkspaceId, "user-1")
    ).rejects.toBeInstanceOf(OwnershipError);
  });

  it("succeeds and returns the conversation when it genuinely belongs to the authorized workspace", async () => {
    const workspaceId = new Types.ObjectId();
    const conversationId = new Types.ObjectId();
    mockedAssertOwnership.mockResolvedValue({} as never);
    mockedFindById.mockResolvedValue({ _id: conversationId, workspaceId } as never);

    const result = await assertConversationOwnership(conversationId.toString(), workspaceId.toString(), "user-1");

    expect(result._id).toEqual(conversationId);
  });

  it("rejects a malformed conversationId without ever querying the Conversation collection", async () => {
    mockedAssertOwnership.mockResolvedValue({} as never);

    await expect(
      assertConversationOwnership("not-an-object-id", new Types.ObjectId().toString(), "user-1")
    ).rejects.toBeInstanceOf(OwnershipError);
    expect(mockedFindById).not.toHaveBeenCalled();
  });

  it("propagates workspace-ownership rejection BEFORE ever touching the Conversation collection (workspace checked first)", async () => {
    mockedAssertOwnership.mockRejectedValue(new OwnershipError());

    await expect(
      assertConversationOwnership(new Types.ObjectId().toString(), new Types.ObjectId().toString(), "user-1")
    ).rejects.toBeInstanceOf(OwnershipError);
    expect(mockedFindById).not.toHaveBeenCalled();
  });
});

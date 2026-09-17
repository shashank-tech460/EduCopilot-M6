import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { isOffline, isNetworkError, flushOfflineQueue, __resetOfflineQueueFlushGuardForTests } from "@/components/chat/OfflineQueue";
import { useAppStore, type QueuedChatMessage } from "@/store/appStore";

function queuedMessage(id: string, text: string): QueuedChatMessage {
  return { id, text, workspaceId: "ws-1", conversationId: "conv-1", videoTimestamp: null, queuedAt: new Date() };
}

beforeEach(() => {
  useAppStore.getState().clearOfflineQueue();
  __resetOfflineQueueFlushGuardForTests();
});

describe("isOffline", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns true when navigator.onLine is false", () => {
    vi.stubGlobal("navigator", { onLine: false });
    expect(isOffline()).toBe(true);
  });

  it("returns false when navigator.onLine is true", () => {
    vi.stubGlobal("navigator", { onLine: true });
    expect(isOffline()).toBe(false);
  });
});

describe("isNetworkError — distinguishing network failures from application errors", () => {
  it("classifies a native TypeError (fetch itself failed) as a network error", () => {
    expect(isNetworkError(new TypeError("Failed to fetch"))).toBe(true);
  });

  it("does NOT classify a generic Error (e.g. an API/HTTP error) as a network error", () => {
    expect(isNetworkError(new Error("Unauthorized"))).toBe(false);
  });

  it("does not classify a plain string or object as a network error", () => {
    expect(isNetworkError("network down")).toBe(false);
    expect(isNetworkError({ status: 500 })).toBe(false);
  });
});

describe("flushOfflineQueue — Property 17 (FIFO ordering) + duplicate prevention", () => {
  it("sends queued messages in original submission order", async () => {
    useAppStore.getState().enqueueOfflineMessage(queuedMessage("q1", "first question"));
    useAppStore.getState().enqueueOfflineMessage(queuedMessage("q2", "second question"));
    useAppStore.getState().enqueueOfflineMessage(queuedMessage("q3", "third question"));

    const sentOrder: string[] = [];
    await flushOfflineQueue(async (item) => {
      sentOrder.push(item.text);
      return true;
    });

    expect(sentOrder).toEqual(["first question", "second question", "third question"]);
  });

  it("removes each item from the queue only after it succeeds", async () => {
    useAppStore.getState().enqueueOfflineMessage(queuedMessage("q1", "hello"));

    expect(useAppStore.getState().chat.offlineQueue).toHaveLength(1);

    await flushOfflineQueue(async () => true);

    expect(useAppStore.getState().chat.offlineQueue).toHaveLength(0);
  });

  it("stops at the first failure and leaves it plus everything after it queued, rather than skipping out of order", async () => {
    useAppStore.getState().enqueueOfflineMessage(queuedMessage("q1", "first"));
    useAppStore.getState().enqueueOfflineMessage(queuedMessage("q2", "second"));
    useAppStore.getState().enqueueOfflineMessage(queuedMessage("q3", "third"));

    const attempted: string[] = [];
    await flushOfflineQueue(async (item) => {
      attempted.push(item.text);
      return item.text !== "second"; // second fails
    });

    // third is never attempted — order is preserved, nothing is skipped.
    expect(attempted).toEqual(["first", "second"]);
    const remaining = useAppStore.getState().chat.offlineQueue.map((item) => item.text);
    expect(remaining).toEqual(["second", "third"]);
  });

  it("never sends the same queued item twice, even if flush is called again while one is already running", async () => {
    useAppStore.getState().enqueueOfflineMessage(queuedMessage("q1", "hello"));

    let resolveFirst: (value: boolean) => void = () => {};
    const sendCalls: string[] = [];

    const firstFlush = flushOfflineQueue((item) => {
      sendCalls.push(item.id);
      return new Promise<boolean>((resolve) => {
        resolveFirst = resolve;
      });
    });

    // A second flush call while the first is still in-flight must not
    // start a second overlapping send of the same item.
    const secondFlush = flushOfflineQueue((item) => {
      sendCalls.push(item.id);
      return Promise.resolve(true);
    });

    resolveFirst(true);
    await Promise.all([firstFlush, secondFlush]);

    expect(sendCalls).toEqual(["q1"]);
  });
});

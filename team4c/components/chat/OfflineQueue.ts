import { useAppStore, type QueuedChatMessage } from "@/store/appStore";

/**
 * Offline Queue — Accion Labs Requirement 8.1/8.2, Property 17 (FIFO
 * ordering on reconnect). Named/located per Task 2.2's exact file path.
 *
 * This is a plain logic module, not a React component or a second store —
 * the actual queue *state* lives in the existing App_Store's
 * `chat.offlineQueue` (extended minimally for this purpose); this file
 * only contains the pure detection/classification helpers and the FIFO
 * flush loop that hooks (useChatStream) call.
 *
 * Deliberately NOT persisted to localStorage/IndexedDB: neither the exact
 * spec text (Requirement 8.1/8.2) nor the OfflineQueue design sample
 * requires surviving a page reload — only "queue locally" and "retry on
 * reconnect" within the current session. Adding persistence here would be
 * inventing a requirement the source document doesn't state.
 */

/**
 * `navigator.onLine` is a hint, not a guarantee (a browser can report
 * "online" while a request still fails) — this function is only used to
 * decide whether to attempt sending at all *before* making a request; the
 * actual authority on "did this fail because of connectivity" is
 * `isNetworkError()` below, applied to a real failed request.
 */
export function isOffline(): boolean {
  return typeof navigator !== "undefined" && navigator.onLine === false;
}

/**
 * Distinguishes a genuine network-level failure (the fetch itself never
 * reached a server — DNS failure, no connection, CORS preflight failure)
 * from an application/HTTP error. The installed AI SDK wraps a real HTTP
 * response (401, 404, 500, etc.) in its own `APICallError` class; a
 * network-level failure surfaces as a native `TypeError` from `fetch`
 * itself (confirmed by reading @ai-sdk/provider-utils's source before
 * writing this, not assumed). Only a TypeError should ever cause a
 * message to be queued — a 401/403/404/500 is an application failure and
 * must continue to use the existing inline error + retry UI unchanged.
 */
export function isNetworkError(error: unknown): boolean {
  return error instanceof TypeError;
}

/**
 * Sends every currently-queued message in strict FIFO order, awaiting
 * each one's full completion (success or failure) before attempting the
 * next — this is both the ordering guarantee (Property 17) and the
 * duplicate-prevention guarantee (never two in-flight sends at once).
 *
 * On success, the item is removed. On failure, the loop stops immediately
 * — the failed item and everything queued after it remain queued for the
 * next reconnect attempt, rather than being skipped out of order.
 *
 * `sendOne` is provided by the caller (useChatStream) since only it has
 * access to the actual `useChat` `sendMessage` function and a way to know
 * when that specific send finished.
 */
// Re-entrancy guard: if a flush is already running (e.g. two "online"
// events fire close together), a second overlapping call must not start —
// that would risk sending the same queued item twice.
let isFlushing = false;

/**
 * TEST-ONLY: resets the re-entrancy guard above. Exists solely because
 * this guard is deliberately process/module-global (not per-hook-
 * instance) — correct in production (there is only ever one real
 * offline queue), but it means an interrupted or not-fully-awaited
 * flush in one test can leave `isFlushing` stuck `true` for every
 * subsequent test in the same file/module registry, silently no-oping
 * their own `flushOfflineQueue` calls. Never imported or called from
 * any non-test code path. Does not alter the FIFO/duplicate-prevention
 * contract in any way — it only resets the guard's own bookkeeping.
 */
export function __resetOfflineQueueFlushGuardForTests(): void {
  isFlushing = false;
}

export async function flushOfflineQueue(
  sendOne: (item: QueuedChatMessage) => Promise<boolean>
): Promise<void> {
  if (isFlushing) {
    return;
  }
  isFlushing = true;

  try {
    // Snapshot at start; each iteration re-reads current state so an item
    // successfully sent by a concurrent path (shouldn't happen given the
    // guard above, but kept defensive) isn't double-processed.
    for (const item of [...useAppStore.getState().chat.offlineQueue]) {
      const stillQueued = useAppStore.getState().chat.offlineQueue.some((q) => q.id === item.id);
      if (!stillQueued) {
        continue;
      }
      const succeeded = await sendOne(item);
      if (succeeded) {
        useAppStore.getState().dequeueOfflineMessage(item.id);
      } else {
        break;
      }
    }
  } finally {
    isFlushing = false;
  }
}

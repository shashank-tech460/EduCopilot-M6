"use client";

import { useEffect, useRef } from "react";
import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";

import { useAppStore, type SourceAttribution, type QueuedChatMessage } from "@/store/appStore";
import { isOffline, isNetworkError, flushOfflineQueue } from "@/components/chat/OfflineQueue";

/**
 * Chat streaming hook — Accion Labs Task 2.1, adapted from the design
 * document's `useChatStream` sample (which shows `ai/react`'s v3/v4-era
 * `handleSubmit`/`input`/flat `content` API). The actually installed
 * versions here (ai@7, @ai-sdk/react@4 — confirmed by reading
 * node_modules/ai/dist/index.d.ts directly, not assumed) use a
 * transport-based API with structured message `parts` instead. This is
 * the "use the correct API for the installed version" adaptation Phase F
 * explicitly calls for — the *behavior* matches the spec exactly; only the
 * API shape differs from the sample.
 *
 * Property 1 (payload completeness) — the request body always includes
 * `workspaceId` and `videoTimestamp`, read fresh via the `body` transport
 * option's function form on every send, not captured once at hook-mount
 * time.
 *
 * The conflict noted in this task's Phase A report is resolved here:
 * `videoTimestamp` is `null` when `video.activeMediaId` is null (no video
 * active) rather than sending the store's numeric default of 0 — matching
 * Property 1's exact wording without changing appStore.ts's types.
 *
 * Requirement 8.1/8.2 (Offline Queue): handled here rather than in
 * ChatPanel, since only this hook has access to `sendMessage`/`status`/
 * `error`. Two integration points:
 *   1. Before sending, `isOffline()` short-circuits straight to the queue
 *      without even attempting a request.
 *   2. `onError` classifies the failure — a real network failure
 *      (`isNetworkError`) queues the message that was just attempted; an
 *      application error (401/404/500/etc.) falls through to the
 *      existing, unchanged `setMessageError` inline-error path.
 */
export function useChatStream(workspaceId: string, conversationId: string | null) {
  // MVP M5 correction: `conversationId` is `null` only while
  // `useActiveConversation` (hooks/useActiveConversation.ts) is still
  // establishing/creating the active Conversation for `workspaceId` --
  // `submitMessage` below refuses to send until it is non-null, so the
  // real Chat UI never operates without an authorized Conversation.
  // Tracks the text of the most recent submitAttempt so onError (which
  // only receives the Error, not the original request) can queue the
  // right message if it turns out to be a network failure.
  const lastAttemptedTextRef = useRef<string | null>(null);
  // Resolves the in-flight flush-loop's per-item promise from onFinish/
  // onError — lets flushOfflineQueue await one queued item fully
  // completing before sending the next (Property 17's FIFO + no-duplicate
  // guarantee), without needing sendMessage() itself to return a promise
  // that resolves on stream completion (it doesn't).
  const flushResolveRef = useRef<((succeeded: boolean) => void) | null>(null);
  // MVP M5 micro-correction: the exact QueuedChatMessage currently being
  // replayed, if any -- set immediately before calling sendMessage() for
  // a replay, cleared after onFinish/onError. A network failure during
  // THIS specific send must requeue using THIS item's own original
  // workspaceId/conversationId/videoTimestamp, never whatever the hook's
  // CURRENT `workspaceId`/`conversationId` parameters happen to be at
  // the moment onError fires -- those can legitimately have changed
  // (the user switched conversations/workspaces) while the replay
  // request was still in flight. `null` means "the send currently in
  // flight (if any) is a normal, non-replay submitMessage() call."
  const replayingItemRef = useRef<QueuedChatMessage | null>(null);

  const { messages, sendMessage, status, error, regenerate, clearError } = useChat({
    transport: new DefaultChatTransport({
      api: "/api/chat",
      body: () => {
        const { activeMediaId, currentTimestamp } = useAppStore.getState().video;
        return {
          workspaceId,
          // MVP M5 correction: the ACTIVE conversation for a normal
          // (non-replay) send. Offline-queue replay overrides this with
          // the queued item's own ORIGINAL conversationId via
          // sendMessage's per-call `body` option (see `handleOnline`
          // below) -- this default is never used for a replay.
          conversationId,
          videoTimestamp: activeMediaId ? currentTimestamp : null,
        };
      },
    }),
    onFinish: ({ message }) => {
      const citationsPart = message.parts.find(
        (part): part is { type: "data-citations"; data: SourceAttribution[] } =>
          part.type === "data-citations"
      );
      useAppStore.getState().addMessage({
        id: message.id,
        role: message.role === "assistant" ? "assistant" : "user",
        content: message.parts
          .filter((part): part is Extract<typeof part, { type: "text" }> => part.type === "text")
          .map((part) => part.text)
          .join(""),
        attributions: citationsPart?.data,
        timestamp: new Date(),
        status: "complete",
      });
      useAppStore.getState().setStreaming(false);
      replayingItemRef.current = null;
      flushResolveRef.current?.(true);
      flushResolveRef.current = null;
    },
    onError: (err) => {
      useAppStore.getState().setStreaming(false);

      if (isNetworkError(err)) {
        const replayingItem = replayingItemRef.current;
        if (replayingItem) {
          // The item being replayed is STILL present in the offline
          // queue -- flushOfflineQueue (components/chat/OfflineQueue.ts)
          // only ever dequeues an item on SUCCESS; on failure it simply
          // breaks out of its loop, leaving the item exactly as it was.
          // Its own original workspaceId/conversationId/videoTimestamp/
          // queuedAt are therefore already correct and untouched --
          // re-enqueueing here (as the pre-correction code did,
          // unconditionally) would create a DUPLICATE entry, and
          // rebuilding it from the hook's CURRENT
          // workspaceId/conversationId (as the branch below does for a
          // genuinely new message) would silently rewrite it to
          // whichever conversation/workspace happens to be active NOW --
          // exactly the bug this correction exists to fix. So: neither
          // action is taken; the existing queued entry is left alone.
        } else {
          const text = lastAttemptedTextRef.current;
          if (text && conversationId) {
            useAppStore.getState().enqueueOfflineMessage({
              id: crypto.randomUUID(),
              text,
              workspaceId,
              conversationId,
              videoTimestamp: useAppStore.getState().video.activeMediaId
                ? useAppStore.getState().video.currentTimestamp
                : null,
              queuedAt: new Date(),
            });
          }
        }
        // Requirement 8.1 — a network failure is handled entirely by the
        // queue notification (rendered in ChatPanel from the queue state
        // itself); it must NOT also populate the existing inline
        // application-error UI, which is reserved for real API/HTTP
        // errors per the error-classification rule.
      } else {
        useAppStore.getState().setMessageError(err.message);
      }

      replayingItemRef.current = null;
      flushResolveRef.current?.(false);
      flushResolveRef.current = null;
    },
  });

  const isStreaming = status === "submitted" || status === "streaming";

  // Keep the App_Store's isStreaming flag (used elsewhere, e.g. a future
  // Dashboard-level indicator) in sync with useChat's own status. This
  // runs as an effect, not during render — calling a store setter directly
  // in the render body would be an impure side effect and risks
  // Strict-Mode double-invocation issues.
  useEffect(() => {
    useAppStore.getState().setStreaming(isStreaming);
  }, [isStreaming]);

  // Requirement 8.2 — automatically retry queued messages when
  // connectivity is restored. The browser's native "online" event, not
  // polling — navigator.onLine is only checked reactively here, never
  // pinged proactively.
  useEffect(() => {
    function handleOnline() {
      flushOfflineQueue((item: QueuedChatMessage) => {
        return new Promise<boolean>((resolve) => {
          flushResolveRef.current = resolve;
          lastAttemptedTextRef.current = item.text;
          // MVP M5 micro-correction: set BEFORE calling sendMessage, so
          // onError can tell "this failure belongs to a replay of THIS
          // exact item" from "this failure belongs to a fresh,
          // normal send" -- cleared in both onFinish and onError.
          replayingItemRef.current = item;
          // Replay MUST use the queued item's own ORIGINAL
          // workspaceId/conversationId/videoTimestamp -- never
          // whichever workspace/conversation/video happens to be
          // active right now (the user may have switched any of them
          // while this item sat in the queue) -- overridden per-call
          // via sendMessage's `body` option, which merges on top of
          // (and here, deliberately overrides) the transport's own
          // `body` function above.
          sendMessage(
            { text: item.text },
            { body: { conversationId: item.conversationId, workspaceId: item.workspaceId, videoTimestamp: item.videoTimestamp } }
          );
        });
      });
    }

    window.addEventListener("online", handleOnline);
    return () => window.removeEventListener("online", handleOnline);
  }, [sendMessage]);

  function submitMessage(text: string) {
    if (!text.trim() || isStreaming || !conversationId) {
      return;
    }

    if (isOffline()) {
      // Requirement 8.1 — queued immediately, without ever attempting a
      // request that's already known to be futile.
      useAppStore.getState().enqueueOfflineMessage({
        id: crypto.randomUUID(),
        text,
        workspaceId,
        conversationId,
        videoTimestamp: useAppStore.getState().video.activeMediaId
          ? useAppStore.getState().video.currentTimestamp
          : null,
        queuedAt: new Date(),
      });
      return;
    }

    lastAttemptedTextRef.current = text;
    replayingItemRef.current = null;
    sendMessage({ text });
  }

  function retry() {
    clearError();
    regenerate();
  }

  return {
    messages,
    submitMessage,
    isStreaming,
    error,
    retry,
    offlineQueue: useAppStore((state) => state.chat.offlineQueue),
  };
}

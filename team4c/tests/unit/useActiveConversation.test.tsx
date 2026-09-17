import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import { useActiveConversation } from "@/hooks/useActiveConversation";
import { useAppStore } from "@/store/appStore";

/**
 * MVP M5 correction — `useActiveConversation` is the ONLY client-side
 * code that establishes a Conversation for the Chat UI to use. It never
 * generates an id itself; it always calls the real, existing
 * `POST /api/workspaces/[id]/conversations` route (mocked here at the
 * `fetch` layer, matching this file's own scope: proving the HOOK's
 * request/reuse/stability logic, not re-testing the route itself, which
 * has its own dedicated test file).
 */

function resetChatState() {
  useAppStore.setState((state) => ({
    chat: { ...state.chat, activeConversationId: null, activeConversationWorkspaceId: null },
  }));
}

beforeEach(() => {
  resetChatState();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const match = /\/api\/workspaces\/([^/]+)\/conversations/.exec(url);
      const workspaceId = match?.[1] ?? "unknown";
      return {
        ok: true,
        json: async () => ({ id: `conv-for-${workspaceId}`, workspaceId, title: "New conversation" }),
      } as Response;
    })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useActiveConversation", () => {
  it("A/1: establishes a real conversation via the server-side creation API — never invents one client-side", async () => {
    const { result } = renderHook(() => useActiveConversation("ws-1"));

    await waitFor(() => expect(result.current).not.toBeNull());

    expect(result.current).toBe("conv-for-ws-1");
    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces/ws-1/conversations",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("8/10: the established conversation remains stable across re-renders of the same workspace", async () => {
    const { result, rerender } = renderHook(({ workspaceId }) => useActiveConversation(workspaceId), {
      initialProps: { workspaceId: "ws-1" },
    });

    await waitFor(() => expect(result.current).not.toBeNull());
    const first = result.current;

    rerender({ workspaceId: "ws-1" });
    rerender({ workspaceId: "ws-1" });

    expect(result.current).toBe(first);
    // Only ONE creation call total -- re-renders never re-create.
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("9/F: switching workspaces establishes a DIFFERENT conversation", async () => {
    const { result, rerender } = renderHook(({ workspaceId }) => useActiveConversation(workspaceId), {
      initialProps: { workspaceId: "ws-1" },
    });
    await waitFor(() => expect(result.current).not.toBeNull());
    const first = result.current;

    rerender({ workspaceId: "ws-2" });
    await waitFor(() => expect(result.current).toBe("conv-for-ws-2"));

    expect(result.current).not.toBe(first);
  });

  it("does not fire a second creation request while one is already in flight for the same workspace", async () => {
    const resolver: { resolve: (() => void) | null } = { resolve: null };
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise((resolve) => {
            resolver.resolve = () =>
              resolve({ ok: true, json: async () => ({ id: "conv-slow", workspaceId: "ws-1" }) } as Response);
          })
      )
    );

    const { rerender } = renderHook(({ workspaceId }) => useActiveConversation(workspaceId), {
      initialProps: { workspaceId: "ws-1" },
    });
    rerender({ workspaceId: "ws-1" });
    rerender({ workspaceId: "ws-1" });

    expect(fetch).toHaveBeenCalledTimes(1);
    resolver.resolve?.();
  });
});

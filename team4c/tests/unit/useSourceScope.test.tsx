import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";

import { useSourceScope } from "@/hooks/useSourceScope";
import { useAppStore } from "@/store/appStore";

function resetChatState() {
  useAppStore.setState((state) => ({
    chat: { ...state.chat, sourceScopeDocumentIds: null },
  }));
}

beforeEach(() => {
  resetChatState();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useSourceScope", () => {
  it("loads the workspace's own source list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.includes("/scope")) {
          return { ok: true, json: async () => ({ document_ids: null }) };
        }
        return {
          ok: true,
          json: async () => [
            { id: "a", originalName: "A.pdf", type: "pdf", status: "ready" },
            { id: "b", originalName: "B.mp4", type: "video", status: "processing" },
          ],
        };
      })
    );

    const { result } = renderHook(() => useSourceScope("ws-1", "conv-1"));

    await waitFor(() => expect(result.current.isLoadingSources).toBe(false));

    expect(result.current.sources).toHaveLength(2);
    expect(result.current.readySources).toHaveLength(1);
    expect(result.current.readySources[0].id).toBe("a");
  });

  it("updateScope PATCHes the real route and stores back the server-returned (validated) scope, not the requested one", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes("/scope")) {
        return { ok: true, json: async () => ({ document_ids: ["a"] }) }; // server dropped "attacker-id"
      }
      return { ok: true, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useSourceScope("ws-1", "conv-1"));
    await waitFor(() => expect(result.current.isLoadingSources).toBe(false));

    await act(async () => {
      await result.current.updateScope(["a", "attacker-id"]);
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/conversations/conv-1/scope",
      expect.objectContaining({ method: "PATCH" })
    );
    expect(useAppStore.getState().chat.sourceScopeDocumentIds).toEqual(["a"]);
  });

  it("updateScope is a no-op when conversationId is null (scope establishment still in flight)", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => [] }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useSourceScope("ws-1", null));
    await waitFor(() => expect(result.current.isLoadingSources).toBe(false));

    await act(async () => {
      await result.current.updateScope(["a"]);
    });

    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/scope"), expect.anything());
  });
});

describe("useSourceScope — MVP M6 correction: conversation scope hydration", () => {
  it("1/2: hydrates the store from the authoritative GET /scope response when a real conversationId is established", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("/scope")) return { ok: true, json: async () => ({ document_ids: ["doc-A"] }) };
      return { ok: true, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useSourceScope("ws-1", "conv-1"));

    await waitFor(() => expect(useAppStore.getState().chat.sourceScopeDocumentIds).toEqual(["doc-A"]));
    expect(fetchMock).toHaveBeenCalledWith("/api/conversations/conv-1/scope");
  });

  it("3: hydrates a multi-document scope correctly", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.includes("/scope")
          ? { ok: true, json: async () => ({ document_ids: ["doc-A", "doc-B"] }) }
          : { ok: true, json: async () => [] }
      )
    );

    renderHook(() => useSourceScope("ws-1", "conv-1"));

    await waitFor(() => expect(useAppStore.getState().chat.sourceScopeDocumentIds).toEqual(["doc-A", "doc-B"]));
  });

  it("4/10: hydrates null (cleared/workspace-wide) correctly, distinct from an empty array", async () => {
    // Pre-seed a stale, WRONG value to prove hydration actually overwrites it.
    useAppStore.getState().setSourceScopeDocumentIds(["stale-doc"]);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.includes("/scope") ? { ok: true, json: async () => ({ document_ids: null }) } : { ok: true, json: async () => [] }
      )
    );

    renderHook(() => useSourceScope("ws-1", "conv-1"));

    await waitFor(() => expect(useAppStore.getState().chat.sourceScopeDocumentIds).toBeNull());
  });

  it("11/explicit-empty: hydrates an explicit empty array distinctly from null", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.includes("/scope") ? { ok: true, json: async () => ({ document_ids: [] }) } : { ok: true, json: async () => [] }
      )
    );

    renderHook(() => useSourceScope("ws-1", "conv-1"));

    await waitFor(() => {
      const value = useAppStore.getState().chat.sourceScopeDocumentIds;
      expect(value).toEqual([]);
      expect(value).not.toBeNull();
    });
  });

  it("6/8: switching between two conversations hydrates each one's OWN scope, with no cross-contamination", async () => {
    const scopesByConversation: Record<string, string[] | null> = {
      "conv-A": ["doc-A"],
      "conv-B": ["doc-B"],
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.includes("/scope")) {
          const conversationId = url.match(/conversations\/([^/]+)\/scope/)?.[1] ?? "";
          return { ok: true, json: async () => ({ document_ids: scopesByConversation[conversationId] ?? null }) };
        }
        return { ok: true, json: async () => [] };
      })
    );

    const { rerender } = renderHook(({ conversationId }) => useSourceScope("ws-1", conversationId), {
      initialProps: { conversationId: "conv-A" },
    });
    await waitFor(() => expect(useAppStore.getState().chat.sourceScopeDocumentIds).toEqual(["doc-A"]));

    rerender({ conversationId: "conv-B" });
    await waitFor(() => expect(useAppStore.getState().chat.sourceScopeDocumentIds).toEqual(["doc-B"]));

    rerender({ conversationId: "conv-A" });
    await waitFor(() => expect(useAppStore.getState().chat.sourceScopeDocumentIds).toEqual(["doc-A"]));
  });

  it("7: a stale, slow response for a PREVIOUS conversation cannot overwrite the CURRENT conversation's already-hydrated scope", async () => {
    let resolveStaleFetch: ((value: unknown) => void) | undefined;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes("conv-STALE")) {
        return new Promise((resolve) => {
          resolveStaleFetch = () => resolve({ ok: true, json: async () => ({ document_ids: ["doc-STALE"] }) });
        });
      }
      if (url.includes("/scope")) {
        return { ok: true, json: async () => ({ document_ids: ["doc-CURRENT"] }) };
      }
      return { ok: true, json: async () => [] };
    });
    vi.stubGlobal("fetch", fetchMock);

    const { rerender } = renderHook(({ conversationId }) => useSourceScope("ws-1", conversationId), {
      initialProps: { conversationId: "conv-STALE" },
    });

    // Switch away BEFORE the slow "conv-STALE" fetch resolves.
    rerender({ conversationId: "conv-CURRENT" });
    await waitFor(() => expect(useAppStore.getState().chat.sourceScopeDocumentIds).toEqual(["doc-CURRENT"]));

    // Now let the stale request finally resolve.
    resolveStaleFetch?.(undefined);
    await new Promise((r) => setTimeout(r, 10));

    // The stale response must NOT have overwritten the current conversation's scope.
    expect(useAppStore.getState().chat.sourceScopeDocumentIds).toEqual(["doc-CURRENT"]);
  });

  it("does not attempt to hydrate when conversationId is null (establishment still in flight)", async () => {
    const fetchMock = vi.fn(async (url: string) => (url.includes("/scope") ? { ok: true, json: async () => ({ document_ids: ["x"] }) } : { ok: true, json: async () => [] }));
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useSourceScope("ws-1", null));
    await new Promise((r) => setTimeout(r, 10));

    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/scope"));
  });
});

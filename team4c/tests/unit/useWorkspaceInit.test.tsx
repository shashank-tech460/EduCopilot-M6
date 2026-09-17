import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

/**
 * Tests useWorkspaceInit against a mocked next-auth/react useSession() and
 * a mocked global fetch — no live network, no live MongoDB, no live Auth.js
 * session. A real QueryClientProvider wraps the hook (React Query itself
 * isn't mocked) so the actual caching/loading-state behavior is exercised,
 * not a stand-in for it.
 */

const useSessionMock = vi.fn();

vi.mock("next-auth/react", () => ({
  useSession: () => useSessionMock(),
}));

import { useWorkspaceInit } from "@/hooks/useWorkspaceInit";
import { useAppStore } from "@/store/appStore";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  useAppStore.getState().logout();
  useSessionMock.mockReturnValue({
    data: { user: { id: "user-1", name: "Sample Student" }, expires: "2099-01-01" },
    status: "authenticated",
  });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "ws-1", name: "DBMS", createdAt: "2026-01-01T00:00:00.000Z" }),
    })
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("useWorkspaceInit", () => {
  it("fetches the workspace for the given id and syncs it into the App_Store", async () => {
    const { result } = renderHook(() => useWorkspaceInit("ws-1"), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.workspace).toEqual({
      id: "ws-1",
      name: "DBMS",
      createdAt: "2026-01-01T00:00:00.000Z",
    });
    expect(useAppStore.getState().workspace).toEqual(result.current.workspace);
  });

  it("syncs the authenticated user's id into the App_Store's session domain", async () => {
    renderHook(() => useWorkspaceInit("ws-1"), { wrapper });

    await waitFor(() => expect(useAppStore.getState().session).toEqual({ userId: "user-1" }));
  });

  it("does not call fetch when workspaceId is null", () => {
    renderHook(() => useWorkspaceInit(null), { wrapper });
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("does not call fetch while unauthenticated, and clears any existing session", async () => {
    useSessionMock.mockReturnValue({ data: null, status: "unauthenticated" });
    useAppStore.getState().setSession({ userId: "stale-user" });

    renderHook(() => useWorkspaceInit("ws-1"), { wrapper });

    expect(global.fetch).not.toHaveBeenCalled();
    await waitFor(() => expect(useAppStore.getState().session).toBeNull());
  });

  it("surfaces a 404 as a workspace-not-found error, without writing bad data to the store", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({ error: "Not found." }) })
    );

    const { result } = renderHook(() => useWorkspaceInit("someone-elses-workspace"), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBe("Workspace not found.");
    expect(useAppStore.getState().workspace).toBeNull();
  });

  it("skips its own fetch when initialData is provided (avoids a duplicate request)", async () => {
    const { result } = renderHook(
      () => useWorkspaceInit("ws-1", { id: "ws-1", name: "DBMS" }),
      { wrapper }
    );

    // initialData means React Query already has data on the very first
    // render — no fetch should have been needed to get there.
    expect(result.current.isLoading).toBe(false);
    expect(result.current.workspace).toEqual({ id: "ws-1", name: "DBMS" });
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

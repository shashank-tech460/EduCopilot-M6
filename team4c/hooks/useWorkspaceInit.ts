"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "next-auth/react";

import { useAppStore, type WorkspaceState } from "@/store/appStore";

/**
 * Workspace initialization hook — Accion Labs Task 1.3.
 *
 * Covers:
 *   Requirement 6.1 — scopes data to the authenticated user's workspace
 *   Requirement 6.2 — loads only the authenticated user's workspace data
 *   Requirement 7.4 — restoring App_Store state (see note below: the
 *     video-timestamp/UI-preference half of this requirement is already
 *     satisfied by Task 1.1's persist/partialize config; this hook is
 *     responsible for the workspace-identity half only)
 *
 * SECURITY NOTE — how the workspace ID is obtained: this hook takes
 * `workspaceId` as a parameter (intended to come from the `/workspace/[id]`
 * route's own params, the same way the existing server-rendered workspace
 * page already gets it) rather than decoding it from a token. The existing
 * architecture supports multiple workspaces per user (Phase 5), so there
 * is no single "the" workspace ID to encode into the JWT. Authorization is
 * enforced server-side regardless — `GET /api/workspaces/[id]` calls the
 * same `assertOwnership()` every other route uses, so a workspace ID for a
 * workspace the caller doesn't own returns 404 here exactly as it does
 * everywhere else in the app.
 *
 * `useSession()` (next-auth/react) is used only to read the safe,
 * server-verified `session.user` shape the same way `auth()` exposes it
 * server-side — never a raw JWT, never a client-decoded token.
 *
 * Duplicate-request avoidance: an optional `initialData` parameter lets a
 * future server component pass down data it already fetched via SSR (the
 * same pattern already used by the dashboard page for its workspace list),
 * so React Query skips its own initial fetch entirely when it's provided.
 */
export function useWorkspaceInit(workspaceId: string | null, initialData?: WorkspaceState) {
  const { data: sessionData, status: sessionStatus } = useSession();

  const {
    data: workspace,
    isLoading,
    isError,
    error,
  } = useQuery<WorkspaceState>({
    queryKey: ["workspace", workspaceId],
    queryFn: async () => {
      const response = await fetch(`/api/workspaces/${workspaceId}`);
      if (!response.ok) {
        throw new Error(
          response.status === 404
            ? "Workspace not found."
            : "Unable to load workspace."
        );
      }
      return response.json();
    },
    enabled: !!workspaceId && sessionStatus === "authenticated",
    initialData,
    // When SSR has already provided initialData, treat it as fresh for a
    // short window so mounting doesn't immediately trigger a redundant
    // background refetch of data the caller just fetched a moment ago.
    // Without this, React Query's default staleTime (0) means initialData
    // is considered stale immediately, defeating the point of passing it.
    staleTime: initialData ? 10_000 : 0,
  });

  // Sync into the existing App_Store (setSession/setWorkspace from Task
  // 1.1) rather than introducing a second place workspace/session identity
  // lives. Only syncs on genuine change, not on every render.
  useEffect(() => {
    if (sessionStatus === "authenticated" && sessionData?.user?.id) {
      useAppStore.getState().setSession({ userId: sessionData.user.id });
    } else if (sessionStatus === "unauthenticated") {
      useAppStore.getState().clearSession();
    }
  }, [sessionStatus, sessionData?.user?.id]);

  useEffect(() => {
    if (workspace) {
      useAppStore.getState().setWorkspace(workspace);
    }
  }, [workspace]);

  return {
    workspace,
    isLoading: isLoading && sessionStatus !== "unauthenticated",
    isError,
    error: error instanceof Error ? error.message : null,
  };
}

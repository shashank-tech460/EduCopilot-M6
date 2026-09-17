"use client";

import { useCallback, useEffect, useState } from "react";

import { useAppStore } from "@/store/appStore";

export interface WorkspaceSourceSummary {
  id: string;
  originalName: string;
  type: "pdf" | "video" | "youtube_url";
  status: "uploading" | "processing" | "ready" | "failed";
}

/**
 * MVP M6 — loads the workspace's own source list (for the picker UI)
 * and provides `updateScope()`, the ONLY way this hook ever changes the
 * conversation's source scope: it always calls the real, authoritative
 * `PATCH /api/conversations/[id]/scope` route and stores back exactly
 * what THAT route returns (the server-validated, possibly-narrowed
 * scope) -- never optimistically trusting whatever the UI asked for.
 *
 * `conversationId === null` (scope establishment still in flight, see
 * useActiveConversation.ts) disables `updateScope` entirely -- there is
 * no conversation yet to attach a scope to.
 */
export function useSourceScope(workspaceId: string, conversationId: string | null) {
  const [sources, setSources] = useState<WorkspaceSourceSummary[]>([]);
  const [isLoadingSources, setIsLoadingSources] = useState(true);
  const selectedDocumentIds = useAppStore((state) => state.chat.sourceScopeDocumentIds);
  const setSourceScopeDocumentIds = useAppStore((state) => state.setSourceScopeDocumentIds);

  useEffect(() => {
    let cancelled = false;

    async function loadSources() {
      setIsLoadingSources(true);
      try {
        const response = await fetch(`/api/workspaces/${workspaceId}/files`);
        if (!response.ok || cancelled) return;
        const data: WorkspaceSourceSummary[] = await response.json();
        if (!cancelled) setSources(data);
      } finally {
        if (!cancelled) setIsLoadingSources(false);
      }
    }

    void loadSources();
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  // MVP M6 correction — hydrates the client-side scope mirror from the
  // AUTHORITATIVE Mongo Conversation record whenever `conversationId` is
  // established or changes (a fresh creation, a reopened existing
  // conversation, or a switch between conversations). Without this,
  // the store's `sourceScopeDocumentIds` only ever changed via this
  // hook's own `updateScope()` calls -- reopening a conversation whose
  // scope was set in an earlier session (or before a browser refresh
  // reset all client state) never re-learned it, even though Mongo
  // still had the real value all along.
  //
  // Race-condition safety (Requirement 5): `cancelled` is captured by
  // THIS effect run's own closure, tied to `conversationId` via the
  // dependency array below -- if `conversationId` changes again before
  // this fetch resolves (the user switched conversations again), the
  // cleanup function sets `cancelled = true` for the STALE request, so
  // its response can never overwrite the newer conversation's
  // just-hydrated (or still-loading) state.
  useEffect(() => {
    if (!conversationId) {
      // No conversation established yet -- nothing to hydrate. Does
      // NOT reset the store to `null` here: `null` is a real, distinct
      // value ("workspace-wide") the actual query path would act on --
      // leaving whatever was there (typically the initial `null`, or a
      // previous conversation's value if this fires mid-switch) is
      // strictly a UI-responsiveness concern, never a security one,
      // since the server always re-resolves the real scope from Mongo
      // on every actual chat request regardless of this mirror's state.
      return;
    }

    let cancelled = false;

    async function hydrateScope() {
      try {
        const response = await fetch(`/api/conversations/${conversationId}/scope`);
        if (!response.ok || cancelled) return;
        const data: { document_ids: string[] | null } = await response.json();
        if (!cancelled) setSourceScopeDocumentIds(data.document_ids);
      } catch {
        // A transient network failure here just means the UI keeps
        // showing whatever it last showed -- the next real chat request
        // still re-resolves the TRUE scope server-side regardless.
      }
    }

    void hydrateScope();
    return () => {
      cancelled = true;
    };
  }, [conversationId, setSourceScopeDocumentIds]);

  const updateScope = useCallback(
    async (documentIds: string[] | null) => {
      if (!conversationId) return;
      const response = await fetch(`/api/conversations/${conversationId}/scope`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_ids: documentIds }),
      });
      if (!response.ok) return;
      const data: { document_ids: string[] | null } = await response.json();
      // The ACTUAL persisted scope (possibly narrower than requested,
      // e.g. an unavailable source was dropped server-side) -- never
      // the optimistic value this hook was asked to set.
      setSourceScopeDocumentIds(data.document_ids);
    },
    [conversationId, setSourceScopeDocumentIds]
  );

  const readySources = sources.filter((source) => source.status === "ready");

  return {
    sources,
    readySources,
    isLoadingSources,
    selectedDocumentIds,
    updateScope,
  };
}

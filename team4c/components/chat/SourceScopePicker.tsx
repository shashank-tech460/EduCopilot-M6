"use client";

import { ChevronDown, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useSourceScope } from "@/hooks/useSourceScope";

const STATUS_LABEL: Record<string, string> = {
  processing: "Processing…",
  failed: "Failed",
  uploading: "Uploading…",
};

/**
 * MVP M6 — lets the user scope chat to specific workspace sources.
 * Purely a thin UI over `useSourceScope` (hooks/useSourceScope.ts) --
 * every change goes through the real, authoritative
 * `PATCH /api/conversations/[id]/scope` route; this component never
 * decides authorization itself.
 */
export function SourceScopePicker({ workspaceId, conversationId }: { workspaceId: string; conversationId: string | null }) {
  const { sources, readySources, isLoadingSources, selectedDocumentIds, updateScope } = useSourceScope(
    workspaceId,
    conversationId
  );

  const selectedSet = new Set(selectedDocumentIds ?? []);
  const invalidatedCount =
    selectedDocumentIds && !isLoadingSources
      ? selectedDocumentIds.filter((id) => !readySources.some((source) => source.id === id)).length
      : 0;

  function toggleSource(documentId: string) {
    const current = selectedDocumentIds ?? [];
    const next = current.includes(documentId) ? current.filter((id) => id !== documentId) : [...current, documentId];
    void updateScope(next.length === 0 ? [] : next);
  }

  function clearScope() {
    void updateScope(null);
  }

  const scopeLabel = describeScope(selectedDocumentIds, readySources);

  return (
    <div className="flex items-center gap-2 border-b px-3 py-2 text-sm text-muted-foreground">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="sm" className="h-7 gap-1 px-2 text-sm font-normal">
            <span className="text-foreground">{scopeLabel}</span>
            <ChevronDown className="h-3.5 w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-64">
          <DropdownMenuLabel>Search sources</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {isLoadingSources && <div className="px-2 py-1.5 text-xs text-muted-foreground">Loading sources…</div>}
          {!isLoadingSources && sources.length === 0 && (
            <div className="px-2 py-1.5 text-xs text-muted-foreground">No materials in this workspace yet.</div>
          )}
          {sources.map((source) => {
            const isReady = source.status === "ready";
            return (
              <DropdownMenuCheckboxItem
                key={source.id}
                checked={selectedSet.has(source.id)}
                disabled={!isReady}
                onCheckedChange={() => toggleSource(source.id)}
              >
                <span className={isReady ? undefined : "text-muted-foreground"}>
                  {source.originalName}
                  {!isReady && ` (${STATUS_LABEL[source.status] ?? source.status})`}
                </span>
              </DropdownMenuCheckboxItem>
            );
          })}
        </DropdownMenuContent>
      </DropdownMenu>

      {selectedDocumentIds && selectedDocumentIds.length > 0 && (
        <Button variant="ghost" size="sm" className="h-7 gap-1 px-2 text-xs" onClick={clearScope}>
          <X className="h-3 w-3" />
          Clear
        </Button>
      )}

      {invalidatedCount > 0 && (
        <span className="text-xs text-amber-600">
          {invalidatedCount === selectedDocumentIds?.length
            ? "Selected source is no longer available."
            : `${invalidatedCount} selected source(s) no longer available.`}
        </span>
      )}
    </div>
  );
}

function describeScope(
  selectedDocumentIds: string[] | null,
  readySources: { id: string; originalName: string }[]
): string {
  if (selectedDocumentIds === null) {
    return "Using all workspace materials";
  }
  const stillReady = selectedDocumentIds.filter((id) => readySources.some((source) => source.id === id));
  if (stillReady.length === 0) {
    return "No sources selected";
  }
  if (stillReady.length === 1) {
    const source = readySources.find((s) => s.id === stillReady[0]);
    return `Using: ${source?.originalName ?? "1 source"}`;
  }
  return `Using ${stillReady.length} selected sources`;
}

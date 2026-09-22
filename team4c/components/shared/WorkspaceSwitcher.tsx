"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ChevronsUpDown, FolderKanban, Plus } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import type { WorkspaceSummary } from "@/components/shared/workspace-dashboard";

/**
 * Phase 6E — workspace switcher for the app shell sidebar.
 *
 * Backed entirely by the existing, already-authorized `GET /api/workspaces`
 * route (returns only the signed-in user's own workspaces — see
 * app/api/workspaces/route.ts). This is UI-only work: no new backend
 * surface, no authorization logic added or changed here. "Rename" is
 * deliberately NOT offered — no PATCH endpoint exists for it (see
 * docs/PHASE_6E_UI_UX_AUDIT.json's backend-capability check), and this
 * phase does not invent one.
 */
export function WorkspaceSwitcher() {
  const params = useParams<{ id?: string }>();
  const activeWorkspaceId = typeof params?.id === "string" ? params.id : undefined;

  const { data: workspaces, isLoading } = useQuery<WorkspaceSummary[]>({
    queryKey: ["workspaces", "switcher"],
    queryFn: async () => {
      const response = await fetch("/api/workspaces");
      if (!response.ok) {
        throw new Error("Unable to load workspaces.");
      }
      return response.json();
    },
    staleTime: 10_000,
  });

  const activeWorkspace = workspaces?.find((workspace) => workspace.id === activeWorkspaceId);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-md border border-sidebar-border bg-sidebar px-2.5 py-2 text-left text-sm transition-colors duration-[var(--duration-sm)] hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
          aria-label="Switch workspace"
        >
          <FolderKanban className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate font-medium">
            {activeWorkspace?.name ?? (activeWorkspaceId ? "Loading…" : "Workspaces")}
          </span>
          <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>Your workspaces</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {isLoading ? (
          <div className="flex flex-col gap-1.5 px-2 py-1.5">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </div>
        ) : workspaces && workspaces.length > 0 ? (
          workspaces.map((workspace) => (
            <DropdownMenuItem key={workspace.id} asChild>
              <Link
                href={`/workspace/${workspace.id}`}
                className={workspace.id === activeWorkspaceId ? "font-medium text-foreground" : undefined}
              >
                {workspace.name}
              </Link>
            </DropdownMenuItem>
          ))
        ) : (
          <div className="px-2 py-1.5 text-xs text-muted-foreground">No workspaces yet.</div>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/dashboard" className="text-muted-foreground">
            <Plus className="h-4 w-4" />
            All workspaces
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

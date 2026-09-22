import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
  /** Denser padding for use inside an already-bordered/card container. */
  compact?: boolean;
}

/**
 * Shared empty-state treatment — replaces the three slightly different
 * ad hoc empty states previously hand-written in ChatPanel, WorkspaceFiles,
 * and WorkspaceDashboard (Phase 6E UI/UX audit, section 4). Purely
 * presentational: callers decide the icon, copy, and optional action.
 */
export function EmptyState({ icon: Icon, title, description, action, className, compact }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-2 rounded-lg border border-dashed border-border text-center",
        compact ? "py-8 px-4" : "py-14 px-6",
        className
      )}
    >
      <div className="mb-1 flex h-11 w-11 items-center justify-center rounded-full bg-muted">
        <Icon className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
      </div>
      <p className="text-sm font-medium">{title}</p>
      {description ? (
        <p className="max-w-[22rem] text-sm text-muted-foreground">{description}</p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

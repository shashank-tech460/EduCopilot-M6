import { cn } from "@/lib/utils";

export type MaterialStatus = "uploading" | "processing" | "ready" | "failed";

const STATUS_LABEL: Record<MaterialStatus, string> = {
  uploading: "Uploading…",
  processing: "Processing…",
  ready: "Ready",
  failed: "Failed",
};

const STATUS_CLASSES: Record<MaterialStatus, string> = {
  uploading: "bg-muted text-muted-foreground",
  processing: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400",
  ready: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400",
  failed: "bg-destructive/10 text-destructive",
};

// Phase 6J: which states get the small pulsing activity dot (§7 — "must
// look active but not distracting"). `ready`/`failed` are resolved
// states and never pulse; a plain Tailwind `animate-pulse` opacity
// pulse is used rather than a spinner so it stays calm at small badge
// size, and it's already suppressed everywhere by the existing global
// `prefers-reduced-motion` rule (globals.css).
const ACTIVE_STATUSES: ReadonlySet<MaterialStatus> = new Set(["uploading", "processing"]);

const DOT_CLASSES: Record<MaterialStatus, string> = {
  uploading: "bg-muted-foreground",
  processing: "bg-amber-500 dark:bg-amber-400",
  ready: "bg-emerald-600 dark:bg-emerald-400",
  failed: "bg-destructive",
};

interface StatusBadgeProps {
  status: MaterialStatus;
  label?: string;
  className?: string;
}

/**
 * Single shared status-badge treatment for material/source lifecycle
 * states — replaces the previously duplicated STATUS_BADGE maps in
 * workspace-files.tsx and SourceScopePicker.tsx (Phase 6E UI/UX audit,
 * section 4), so any future status color contract only needs deciding
 * once. `transition-colors` gives a smooth cross-fade when a material's
 * status prop changes (uploading -> processing -> ready) instead of an
 * abrupt swap.
 */
export function StatusBadge({ status, label, className }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium transition-colors duration-[var(--duration-md)]",
        STATUS_CLASSES[status],
        className
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 shrink-0 rounded-full",
          DOT_CLASSES[status],
          ACTIVE_STATUSES.has(status) && "animate-pulse"
        )}
        aria-hidden="true"
      />
      {label ?? STATUS_LABEL[status]}
    </span>
  );
}

"use client";

import { CheckCircle2, X, XCircle, Info } from "lucide-react";

import { useToastStore } from "@/store/useToastStore";
import { cn } from "@/lib/utils";

// Phase 6I: tinted icon badge + glass card, matching the citation-chip/
// material-card accent pattern used everywhere else, rather than a flat
// solid-color block. Text stays on `--card`/`--popover` (foreground
// tokens, already contrast-verified) instead of colored backgrounds, so
// long toast copy never risks the same "text-on-saturated-color"
// contrast trap the Phase 6I audit found and fixed elsewhere.
const VARIANT_STYLES = {
  default: "border-border/70",
  destructive: "border-destructive/40",
  success: "border-emerald-500/40",
};

const VARIANT_ICON_WRAP = {
  default: "bg-brand-indigo/15 text-brand-indigo",
  destructive: "bg-destructive/15 text-destructive",
  success: "bg-emerald-500/15 text-emerald-400",
};

const VARIANT_ICON = {
  default: Info,
  destructive: XCircle,
  success: CheckCircle2,
};

/**
 * Renders active toasts from useToastStore. Mounted once in the root
 * layout (components/shared/auth-session-provider.tsx's sibling, added to
 * app/layout.tsx) so any component can call toast(...) from
 * store/useToastStore.ts without prop-drilling a callback.
 *
 * Phase 6I: entrance is a slide+fade in (CSS keyframe); exit reads the
 * store's `leaving` flag (set ~220ms before actual removal) to play a
 * matching slide+fade out instead of the toast just disappearing.
 */
export function Toaster() {
  const toasts = useToastStore((state) => state.toasts);
  const dismissToast = useToastStore((state) => state.dismissToast);

  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2">
      {toasts.map((t) => {
        const Icon = VARIANT_ICON[t.variant ?? "default"];
        return (
          <div
            key={t.id}
            role="status"
            className={cn(
              "glass-panel pointer-events-auto flex items-start gap-3 rounded-lg border p-4 shadow-[var(--shadow-lg)] transition-[opacity,transform] duration-[var(--duration-md)] ease-[var(--ease-standard)]",
              t.leaving ? "translate-x-2 opacity-0" : "animate-fade-up-in opacity-100",
              VARIANT_STYLES[t.variant ?? "default"]
            )}
          >
            <span
              className={cn(
                "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
                VARIANT_ICON_WRAP[t.variant ?? "default"]
              )}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden="true" />
            </span>
            <div className="flex-1 pt-0.5 text-sm">
              <p className="font-medium text-foreground">{t.title}</p>
              {t.description ? <p className="mt-0.5 text-muted-foreground">{t.description}</p> : null}
            </div>
            <button
              type="button"
              onClick={() => dismissToast(t.id)}
              aria-label="Dismiss notification"
              className="text-muted-foreground opacity-70 transition-opacity hover:opacity-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

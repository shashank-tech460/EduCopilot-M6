"use client";

import { CheckCircle2, X, XCircle, Info } from "lucide-react";

import { useToastStore } from "@/store/useToastStore";
import { cn } from "@/lib/utils";

const VARIANT_STYLES = {
  default: "border bg-background text-foreground",
  destructive: "border-destructive/50 bg-destructive text-destructive-foreground",
  success: "border-emerald-600/50 bg-emerald-600 text-white",
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
              "pointer-events-auto flex items-start gap-3 rounded-lg border p-4 shadow-lg",
              VARIANT_STYLES[t.variant ?? "default"]
            )}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="flex-1 text-sm">
              <p className="font-medium">{t.title}</p>
              {t.description ? <p className="mt-0.5 opacity-90">{t.description}</p> : null}
            </div>
            <button
              type="button"
              onClick={() => dismissToast(t.id)}
              aria-label="Dismiss notification"
              className="opacity-70 transition-opacity hover:opacity-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

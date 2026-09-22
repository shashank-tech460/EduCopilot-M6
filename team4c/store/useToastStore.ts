import { create } from "zustand";

export interface Toast {
  id: string;
  title: string;
  description?: string;
  variant?: "default" | "destructive" | "success";
  /** Phase 6I: true for the last ~250ms before removal, so Toaster can
   * play an exit transition instead of the toast just vanishing. */
  leaving?: boolean;
}

interface ToastStore {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, "id" | "leaving">) => void;
  dismissToast: (id: string) => void;
}

const EXIT_ANIMATION_MS = 220;

/**
 * Minimal, dependency-free toast system built on Zustand (already a
 * project dependency for other cross-component state, per
 * docs/decisions.md §6) rather than adding a dedicated toast library for
 * what's fundamentally a small amount of UI state.
 */
export const useToastStore = create<ToastStore>((set, get) => ({
  toasts: [],
  addToast: (toast) => {
    const id = crypto.randomUUID();
    set((state) => ({ toasts: [...state.toasts, { ...toast, id }] }));
    setTimeout(() => {
      get().dismissToast(id);
    }, 4000);
  },
  dismissToast: (id) => {
    // Marks the toast as leaving first so Toaster can render its exit
    // transition, then actually removes it once that transition would
    // have finished — a manual "Dismiss" click gets the same animation
    // as an auto-dismiss, not an abrupt removal.
    set((state) => ({
      toasts: state.toasts.map((t) => (t.id === id ? { ...t, leaving: true } : t)),
    }));
    setTimeout(() => {
      set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
    }, EXIT_ANIMATION_MS);
  },
}));

/** Convenience helper — `toast({ title: "...", variant: "success" })`. */
export function toast(input: Omit<Toast, "id">) {
  useToastStore.getState().addToast(input);
}

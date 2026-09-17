import { create } from "zustand";

export interface Toast {
  id: string;
  title: string;
  description?: string;
  variant?: "default" | "destructive" | "success";
}

interface ToastStore {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, "id">) => void;
  dismissToast: (id: string) => void;
}

/**
 * Minimal, dependency-free toast system built on Zustand (already a
 * project dependency for other cross-component state, per
 * docs/decisions.md §6) rather than adding a dedicated toast library for
 * what's fundamentally a small amount of UI state.
 */
export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  addToast: (toast) => {
    const id = crypto.randomUUID();
    set((state) => ({ toasts: [...state.toasts, { ...toast, id }] }));
    setTimeout(() => {
      set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
    }, 4000);
  },
  dismissToast: (id) => {
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
  },
}));

/** Convenience helper — `toast({ title: "...", variant: "success" })`. */
export function toast(input: Omit<Toast, "id">) {
  useToastStore.getState().addToast(input);
}

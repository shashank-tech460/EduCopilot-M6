"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";

interface PanelErrorBoundaryProps {
  /** Shown in the fallback UI, e.g. "Chat", "Video", "Files" — keeps the
   * generic message specific enough to be useful without exposing
   * implementation details. */
  panelName: string;
  children: ReactNode;
}

interface PanelErrorBoundaryState {
  hasError: boolean;
  /** Bumped on Retry and used as a key on the wrapped children below, so
   * retrying forces a genuinely fresh mount of the crashed subtree rather
   * than re-rendering the exact same (already-thrown) element tree in
   * place, which would just throw again immediately for a deterministic
   * bug. */
  resetKey: number;
}

/**
 * PanelErrorBoundary — Accion Labs Requirement 1.5 / Task 8.2.
 *
 * A React error boundary (class component — no hook-based equivalent
 * exists in React for this) wrapping exactly one Dashboard panel. Three
 * independent instances (one per panel, see workspace-dashboard-shell.tsx)
 * mean a crash in one panel's render never propagates past its own
 * boundary — the other two panels are unrelated React subtrees and keep
 * working normally, per Task 8.2's explicit "do not use one shared
 * boundary" instruction.
 *
 * This is a DIFFERENT failure mode than the existing app/error.tsx
 * (Next.js's route-level boundary, already handling server-side workspace
 * data-fetch failures broadly — untouched, not duplicated here). This
 * boundary catches CLIENT-SIDE rendering/runtime errors thrown while a
 * panel is mounted, independent of whether the initial server fetch
 * succeeded.
 */
export class PanelErrorBoundary extends Component<PanelErrorBoundaryProps, PanelErrorBoundaryState> {
  state: PanelErrorBoundaryState = { hasError: false, resetKey: 0 };

  static getDerivedStateFromError(): Partial<PanelErrorBoundaryState> {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // Requirement 1.5's console-logging clause. The full error and React's
    // component stack are logged — useful for debugging — but nothing is
    // ever rendered into the DOM from `error`/`errorInfo` (see render()
    // below), so no internal detail reaches the page itself.
    console.error(`[${this.props.panelName} panel] render error:`, error, errorInfo);
  }

  handleRetry = () => {
    this.setState((state) => ({ hasError: false, resetKey: state.resetKey + 1 }));
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-6 text-center">
          <AlertTriangle className="h-8 w-8 text-destructive" aria-hidden="true" />
          <p className="text-sm font-medium">
            Something went wrong while loading this panel.
          </p>
          <Button type="button" variant="outline" size="sm" onClick={this.handleRetry}>
            Retry
          </Button>
        </div>
      );
    }

    return <div key={this.state.resetKey}>{this.props.children}</div>;
  }
}

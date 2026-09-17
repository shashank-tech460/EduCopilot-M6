"use client";

import { FileText, Video } from "lucide-react";

import { useAppStore, type SourceAttribution as SourceAttributionType } from "@/store/appStore";
import { formatTimestamp } from "@/lib/formatTimestamp";

interface SourceAttributionProps {
  attribution: SourceAttributionType;
}

/**
 * Source_Attribution — Accion Labs Requirement 3.
 *
 * 3.1 — renders source type (icon), filename, and location reference.
 * 3.2 — clicking a video timestamp calls the EXISTING App_Store action
 *       (`setVideoTimestamp`) that VideoPlayer already subscribes to for
 *       seek commands (Requirement 4.2, built in Step 4) — no new video
 *       state/action is introduced here.
 * 3.3 — clicking a PDF page opens the file's real URL with a `#page=N`
 *       fragment, which browsers' built-in PDF viewers use to scroll to
 *       that page. This project has no in-app PDF viewer (confirmed by
 *       inspection before implementing), so this is the smallest honest
 *       mechanism available without building a new subsystem or faking
 *       navigation — it opens the actual file at the actual page via a
 *       real browser capability, not a scroll position within this
 *       Dashboard (a disclosed limitation, not claimed as more than it is).
 * 3.4 — visually distinguished via background, icon, and underline.
 * 3.5 — `attribution.disabled` is computed server-side (see
 *       app/api/chat/route.ts's use of the existing lib/workspaceFilter.ts)
 *       and simply rendered here — this component does not independently
 *       decide whether a source is available, and never makes a disabled
 *       attribution clickable.
 *
 * No tooltip UI component exists in this project (checked before
 * implementing — no @radix-ui/react-tooltip is installed either), so the
 * native `title` attribute is used for Requirement 3.5's tooltip rather
 * than adding a new dependency for one small piece of UI.
 */
export function SourceAttribution({ attribution }: SourceAttributionProps) {
  const isPdf = attribution.type === "pdf_page";
  const Icon = isPdf ? FileText : Video;
  const locationLabel = isPdf
    ? `Page ${attribution.location}`
    : formatTimestamp(attribution.location);

  const baseClasses =
    "inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium underline underline-offset-2";

  if (attribution.disabled) {
    return (
      <span
        className={`${baseClasses} cursor-not-allowed border-muted bg-muted text-muted-foreground no-underline opacity-60`}
        aria-disabled="true"
        title="Source unavailable in this workspace"
      >
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        {attribution.sourceFile} · {locationLabel}
      </span>
    );
  }

  function handleClick() {
    if (isPdf) {
      if (attribution.fileUrl) {
        window.open(`${attribution.fileUrl}#page=${attribution.location}`, "_blank", "noopener,noreferrer");
      }
      return;
    }
    // Requirement 3.2 — the existing seek mechanism: VideoPlayer already
    // subscribes to this exact store field to accept seek commands.
    useAppStore.getState().setVideoTimestamp(attribution.location);
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`${baseClasses} border-primary/30 bg-primary/10 text-primary hover:bg-primary/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {attribution.sourceFile} · {locationLabel}
    </button>
  );
}

"use client";

import { FileText, Video } from "lucide-react";

import { useAppStore, type SourceAttribution as SourceAttributionType } from "@/store/appStore";
import { formatTimestamp } from "@/lib/formatTimestamp";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

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

  // Phase 6J: `max-w-full` was unbounded before — a real long video/PDF
  // title (confirmed live: "Java OOPs in One Shot | Object Oriented
  // Programming | Java Language | Placement Course") wrapped across 2-3
  // lines PER chip, and with 5 citations on one answer the citation row
  // visually dominated the rest of the message. `sourceFile` is now
  // truncated with an ellipsis inside a capped-width span (full title
  // still in the DOM/accessible name — CSS truncation doesn't remove
  // text content — and still available via the tooltip below and the
  // native `title` attribute), while the short, always-important
  // location label (page/timestamp) stays outside that span so it's
  // never the part that gets clipped.
  const baseClasses =
    "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium underline underline-offset-2 max-w-full";
  // Distinct accent per source type (PDF = indigo, video = cyan) — a
  // small, real visual differentiation matching the master prompt's own
  // two example formats, not a change to the underlying citation data.
  //
  // Phase 6I: uses `--brand-indigo` rather than `--primary` for the PDF
  // accent's TEXT color specifically. `--primary` is deliberately tuned
  // dark (Phase 6H) so *white* button text passes AA on a `--primary`
  // background — but that makes it fail AA (~2.7:1, need 4.5:1) when
  // reused as small colored text on a dark card, which is exactly this
  // chip's case. `--brand-indigo` is the lighter sibling token built for
  // this (verified ~4.7:1 on `--card` via a live contrast sweep).
  const accentClasses = isPdf
    ? "border-primary/30 bg-primary/10 text-brand-indigo hover:bg-primary/20"
    : "border-brand-cyan/30 bg-brand-cyan/10 text-brand-cyan hover:bg-brand-cyan/20";

  if (attribution.disabled) {
    return (
      <span
        className={`${baseClasses} cursor-not-allowed border-muted bg-muted text-muted-foreground no-underline opacity-60`}
        aria-disabled="true"
        title="Source unavailable in this workspace"
      >
        <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span className="max-w-[10rem] truncate">{attribution.sourceFile}</span>
        <span className="shrink-0">· {locationLabel}</span>
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
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={handleClick}
          className={`${baseClasses} ${accentClasses} transition-[box-shadow,background-color] duration-[var(--duration-sm)] hover:shadow-[var(--shadow-sm)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
        >
          <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span className="max-w-[10rem] truncate">{attribution.sourceFile}</span>
          <span className="shrink-0">· {locationLabel}</span>
        </button>
      </TooltipTrigger>
      <TooltipContent side="top">
        <p className="font-medium text-foreground">Evidence behind this answer</p>
        <p className="mt-0.5 text-muted-foreground">
          {isPdf ? "PDF" : "Video"} · {attribution.sourceFile} · {locationLabel}
        </p>
      </TooltipContent>
    </Tooltip>
  );
}

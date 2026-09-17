import { AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { UploadState } from "@/store/appStore";

interface UploadTrackerProps {
  upload: UploadState;
  onRetry: (id: string) => void;
}

/**
 * Upload_Tracker — Accion Labs Task 6.1 / Requirement 5.2, 5.3.
 *
 * Pure presentational component: receives one App_Store `UploadState`
 * record and renders it. Does not know how uploads happen (XHR, fetch,
 * etc.) or where the state lives beyond the shape it's given — the actual
 * upload mechanics live in WorkspaceFiles, which owns the App_Store
 * `uploads` domain entries this component displays.
 *
 * Requirement 5.2 fields shown: filename, percentage, progress bar,
 * estimated time remaining. Requirement 5.3 status display covers the
 * uploading/failed states this component actually needs to render;
 * processing/ready are shown in the main materials list once the upload
 * itself finishes (see WorkspaceFiles), not here.
 */
export function UploadTracker({ upload, onRetry }: UploadTrackerProps) {
  const isFailed = upload.status === "failed";

  return (
    <div className="flex flex-col gap-1.5 rounded-md border p-3" data-testid="upload-tracker">
      <div className="flex items-center justify-between gap-2">
        <p className="min-w-0 truncate text-sm font-medium">{upload.fileName}</p>
        {isFailed ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onRetry(upload.id)}
          >
            Retry
          </Button>
        ) : (
          <span className="shrink-0 text-xs text-muted-foreground">
            {Math.round(upload.progress)}%
          </span>
        )}
      </div>

      {isFailed ? (
        <p className="flex items-center gap-1.5 text-xs text-destructive">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          {upload.error ?? "Upload failed."}
        </p>
      ) : (
        <>
          <div
            className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuenow={Math.round(upload.progress)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Uploading ${upload.fileName}`}
          >
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${Math.min(100, Math.max(0, upload.progress))}%` }}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            {upload.estimatedTimeRemaining === null
              ? "Calculating…"
              : formatEta(upload.estimatedTimeRemaining)}
          </p>
        </>
      )}
    </div>
  );
}

function formatEta(seconds: number): string {
  if (seconds < 1) {
    return "Almost done…";
  }
  if (seconds < 60) {
    return `About ${Math.ceil(seconds)}s remaining`;
  }
  const minutes = Math.ceil(seconds / 60);
  return `About ${minutes} minute${minutes === 1 ? "" : "s"} remaining`;
}

"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, Film, Link as LinkIcon, Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "@/store/useToastStore";
import { useAppStore, type UploadState } from "@/store/appStore";
import { UploadTracker } from "@/components/files/UploadTracker";
import { validateUploadedFile } from "@/lib/validation";

export interface MaterialSummary {
  id: string;
  originalName: string;
  type: "pdf" | "video" | "youtube_url";
  status: "uploading" | "processing" | "ready" | "failed";
  processingError: string | null;
  createdAt: string;
  /**
   * Added for Accion Labs Step 4 (Video_Player): the client previously had
   * no way to know where a file's actual playable bytes/URL live.
   * Required for Requirement 4.1 (playback of workspace MP4s and YouTube
   * URLs) — without it, VideoPlayer would have no `src` to play. Purely
   * additive; does not change WorkspaceFiles' own UI or behavior.
   */
  storageUrl: string;
  /**
   * Added for Accion Labs Requirement 5.6 (File_Manager must display file
   * size). Null for youtube_url materials, which have no local bytes.
   */
  sizeBytes: number | null;
}

interface WorkspaceFilesProps {
  workspaceId: string;
  initialMaterials: MaterialSummary[];
}

type MaterialTab = "pdf" | "video" | "youtube_url";

const TAB_LABEL: Record<MaterialTab, string> = {
  pdf: "Upload PDF",
  video: "Upload MP4",
  youtube_url: "Add YouTube URL",
};

const TYPE_ICON: Record<MaterialSummary["type"], React.ComponentType<{ className?: string }>> = {
  pdf: FileText,
  video: Film,
  // lucide-react no longer ships brand icons (e.g. a literal YouTube logo)
  // in this version — a generic external-link icon communicates "this
  // points somewhere else" without depending on a specific brand's mark.
  youtube_url: LinkIcon,
};

const STATUS_LABEL: Record<MaterialSummary["status"], string> = {
  uploading: "Uploading…",
  processing: "Processing…",
  ready: "Ready",
  failed: "Failed",
};

const STATUS_BADGE: Record<MaterialSummary["status"], string> = {
  uploading: "bg-muted text-muted-foreground",
  processing: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-400",
  ready: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-400",
  failed: "bg-destructive/10 text-destructive",
};

const TYPE_LABEL: Record<MaterialSummary["type"], string> = {
  pdf: "PDF",
  video: "MP4",
  youtube_url: "YouTube",
};

/** Requirement 5.6 — file size display. Null (YouTube URLs) renders nothing. */
function formatBytes(bytes: number | null): string | null {
  if (bytes === null || bytes === undefined) {
    return null;
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Requirement 5.6 — upload date display.
 *
 * Uses an EXPLICIT locale ("en-US"), not `undefined`. Passing `undefined`
 * lets `Intl.DateTimeFormat` fall back to the runtime's default locale —
 * which is the Node.js server process's locale during SSR, but the
 * browser's own locale setting during client-side rendering. Those two
 * can genuinely differ (e.g. server defaults to en-US → "Aug 28, 2026";
 * a browser set to en-GB → "28 Aug 2026"), which is exactly the textbook
 * cause of a React hydration mismatch on locale-dependent formatting.
 * Pinning the locale explicitly makes the output identical on both sides
 * regardless of either environment's actual locale configuration.
 */
export function formatUploadDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * Client component handling the three material-input modes and the
 * existing-materials list. Mirrors the create/delete + router.refresh()
 * pattern already used by WorkspaceDashboard (Phase 5) for consistency.
 */
export function WorkspaceFiles({ workspaceId, initialMaterials }: WorkspaceFilesProps) {
  const router = useRouter();
  const [materials, setMaterials] = useState(initialMaterials);
  // Reactive subscription (not getState()) so the UI actually re-renders as
  // xhr.upload.onprogress fires — getState() elsewhere in this file is used
  // only inside event handlers/callbacks, where a snapshot read is correct.
  const uploads = useAppStore((state) => state.uploads);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<MaterialTab>("pdf");
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [selectedFile, setSelectedFile] = useState<globalThis.File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<MaterialSummary | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function resetForm() {
    setYoutubeUrl("");
    setSelectedFile(null);
    setError(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  /**
   * Performs the actual XHR-based upload for a PDF/MP4 material, tracked
   * via the App_Store's `uploads` domain (Task 1.1 — reused as-is, not
   * duplicated). Used both for the initial submit and for Retry, so a
   * failed upload can be re-attempted with the exact same File object
   * without the user reselecting it (Property 18).
   *
   * XMLHttpRequest is used instead of fetch specifically because fetch
   * provides no browser upload-progress events — `xhr.upload.onprogress`
   * is the only way to get real, byte-driven percentage/ETA (Requirement
   * 5.2), not a timer or animation standing in for one.
   */
  function uploadFile(uploadId: string, file: globalThis.File, materialType: "pdf" | "video") {
    const startTime = Date.now();

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/workspaces/${workspaceId}/files`);

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) {
        return;
      }
      const progress = (event.loaded / event.total) * 100;
      const elapsedSeconds = (Date.now() - startTime) / 1000;
      // "Calculating…" (null) until there's enough real data to derive a
      // meaningful rate — avoids a divide-by-zero and wild first-tick
      // estimates, per the "do not invent unrealistic ETA values" rule.
      const estimatedTimeRemaining =
        event.loaded > 0 && elapsedSeconds > 0.2
          ? (event.total - event.loaded) / (event.loaded / elapsedSeconds)
          : null;

      useAppStore.getState().updateUpload(uploadId, { progress, estimatedTimeRemaining });
    };

    xhr.onload = () => {
      let data: { error?: string; id?: string; originalName?: string } | null = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        useAppStore.getState().updateUpload(uploadId, {
          status: "failed",
          error: xhr.status === 413 ? "That file is too large to upload." : "Unable to upload material.",
        });
        return;
      }

      if (xhr.status < 200 || xhr.status >= 300) {
        useAppStore.getState().updateUpload(uploadId, {
          status: "failed",
          error: data?.error ?? "Something went wrong.",
        });
        return;
      }

      setMaterials((prev) => [data as MaterialSummary, ...prev]);
      useAppStore.getState().removeUpload(uploadId);
      toast({ title: "Material added", description: data?.originalName, variant: "success" });
      router.refresh();
    };

    xhr.onerror = () => {
      useAppStore
        .getState()
        .updateUpload(uploadId, { status: "failed", error: "Network error. Please try again." });
    };

    const formData = new FormData();
    formData.set("type", materialType);
    formData.set("file", file);
    xhr.send(formData);
  }

  function handleRetry(uploadId: string) {
    const upload = useAppStore.getState().uploads[uploadId];
    if (!upload?.fileRef) {
      return;
    }
    useAppStore.getState().updateUpload(uploadId, { status: "uploading", progress: 0, error: undefined });
    uploadFile(uploadId, upload.fileRef, upload.fileType === "pdf" ? "pdf" : "video");
  }

  /**
   * Fixes the reported gap: clicking a ready Learning Materials item
   * previously did nothing at all — there was no interaction wired up,
   * only Delete. This reuses existing mechanisms rather than inventing
   * new ones:
   *   - Video/YouTube: updates the App_Store's existing `activeMediaId`
   *     (Task 1.1's action, already consumed by VideoPlayer/
   *     WorkspaceDashboardShell) — no new state introduced.
   *   - PDF: opens the material's real, workspace-authorized `storageUrl`
   *     in a new tab, the exact same technique already used by
   *     SourceAttribution's PDF citations (components/chat/
   *     SourceAttribution.tsx) — not a new PDF-viewing mechanism.
   * Only ever invoked for `status === "ready"` materials (enforced at the
   * call site below), so processing/failed/uploading items are never
   * selectable — matching the "only ready/valid materials" requirement.
   */
  function handleSelectMaterial(material: MaterialSummary) {
    if (material.type === "pdf") {
      window.open(material.storageUrl, "_blank", "noopener,noreferrer");
      return;
    }
    useAppStore.getState().setActiveMedia(material.id);
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (activeTab === "youtube_url") {
      // YouTube has no bytes to track upload progress for — this path is a
      // small JSON-ish POST, so the existing fetch-based flow is kept
      // exactly as-is rather than routed through the upload tracker.
      setIsSubmitting(true);
      try {
        const formData = new FormData();
        formData.set("type", "youtube_url");
        formData.set("youtubeUrl", youtubeUrl);

        const response = await fetch(`/api/workspaces/${workspaceId}/files`, {
          method: "POST",
          body: formData,
        });

        let data: { error?: string; id?: string; originalName?: string } | null = null;
        try {
          data = await response.json();
        } catch {
          setError("Unable to add material. Please try again.");
          return;
        }

        if (!response.ok) {
          setError(data?.error ?? "Something went wrong.");
          return;
        }

        setMaterials((prev) => [data as MaterialSummary, ...prev]);
        resetForm();
        setDialogOpen(false);
        toast({ title: "Material added", description: data?.originalName, variant: "success" });
        router.refresh();
      } catch {
        setError("Something went wrong. Please try again.");
      } finally {
        setIsSubmitting(false);
      }
      return;
    }

    // Requirement 5.4: validate type/size BEFORE initiating the upload —
    // previously this only happened server-side, after the request (and
    // for a large file, a meaningful amount of upload time) had already
    // started. validateUploadedFile() is the same pure function the API
    // route uses, so client and server agree on what's valid.
    if (!selectedFile) {
      setError("Choose a file first.");
      return;
    }
    const materialType = activeTab as "pdf" | "video";
    const { valid, error: validationError } = validateUploadedFile(selectedFile, materialType);
    if (!valid) {
      setError(validationError ?? "Invalid file.");
      return;
    }

    const uploadId = crypto.randomUUID();
    const uploadRecord: UploadState = {
      id: uploadId,
      fileName: selectedFile.name,
      fileType: materialType === "video" ? "mp4" : "pdf",
      fileSize: selectedFile.size,
      uploadDate: new Date(),
      progress: 0,
      estimatedTimeRemaining: null,
      status: "uploading",
      fileRef: selectedFile,
    };
    useAppStore.getState().addUpload(uploadId, uploadRecord);

    uploadFile(uploadId, selectedFile, materialType);
    resetForm();
    setDialogOpen(false);
  }

  async function handleConfirmDelete() {
    if (!pendingDelete) return;
    const { id, originalName } = pendingDelete;
    setDeletingId(id);

    try {
      const response = await fetch(`/api/workspaces/${workspaceId}/files/${id}`, {
        method: "DELETE",
      });

      if (!response.ok) {
        toast({
          title: "Couldn't delete material",
          description: "Please try again.",
          variant: "destructive",
        });
        return;
      }

      setMaterials((prev) => prev.filter((material) => material.id !== id));
      toast({ title: "Material deleted", description: originalName });
      router.refresh();
    } catch {
      toast({
        title: "Couldn't delete material",
        description: "Please try again.",
        variant: "destructive",
      });
    } finally {
      setDeletingId(null);
      setPendingDelete(null);
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>Learning Materials</CardTitle>
        <Dialog
          open={dialogOpen}
          onOpenChange={(open) => {
            setDialogOpen(open);
            if (!open) resetForm();
          }}
        >
          <DialogTrigger asChild>
            <Button size="sm">
              <Plus className="h-4 w-4" />
              Add Material
            </Button>
          </DialogTrigger>
          <DialogContent>
            <form onSubmit={handleSubmit}>
              <DialogHeader>
                <DialogTitle>Add course material</DialogTitle>
                <DialogDescription>
                  Upload a PDF, an MP4 lecture recording, or link a YouTube video.
                </DialogDescription>
              </DialogHeader>

              <div className="flex gap-2 py-4">
                {(Object.keys(TAB_LABEL) as MaterialTab[]).map((tab) => (
                  <Button
                    key={tab}
                    type="button"
                    size="sm"
                    variant={activeTab === tab ? "default" : "outline"}
                    onClick={() => {
                      setActiveTab(tab);
                      setError(null);
                    }}
                  >
                    {TAB_LABEL[tab]}
                  </Button>
                ))}
              </div>

              {activeTab === "youtube_url" ? (
                <div key="youtube-url-field" className="flex flex-col gap-1.5">
                  <Label htmlFor="youtube-url">YouTube URL</Label>
                  <Input
                    id="youtube-url"
                    placeholder="https://www.youtube.com/watch?v=..."
                    value={youtubeUrl}
                    onChange={(e) => setYoutubeUrl(e.target.value)}
                    aria-invalid={!!error}
                  />
                </div>
              ) : (
                <div key="file-upload-field" className="flex flex-col gap-1.5">
                  <Label htmlFor="material-file">
                    {activeTab === "pdf" ? "PDF file" : "MP4 file"}
                  </Label>
                  <Input
                    id="material-file"
                    ref={fileInputRef}
                    type="file"
                    accept={activeTab === "pdf" ? "application/pdf" : "video/mp4"}
                    onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
                    aria-invalid={!!error}
                  />
                </div>
              )}

              {error ? <p className="mt-2 text-xs text-destructive">{error}</p> : null}

              <DialogFooter className="mt-4">
                <Button type="submit" disabled={isSubmitting}>
                  {isSubmitting ? "Adding…" : "Add Material"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {Object.values(uploads).length > 0 ? (
          <div className="flex flex-col gap-2">
            {Object.values(uploads).map((upload) => (
              <UploadTracker key={upload.id} upload={upload} onRetry={handleRetry} />
            ))}
          </div>
        ) : null}

        {materials.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-md border border-dashed py-8 text-center">
            <p className="text-sm font-medium">No materials yet</p>
            <p className="text-xs text-muted-foreground">
              Upload a PDF, an MP4 lecture, or add a YouTube link to get started.
            </p>
          </div>
        ) : (
          materials.map((material) => {
            const Icon = TYPE_ICON[material.type];
            return (
              <div
                key={material.id}
                className="flex items-center justify-between gap-3 rounded-md border p-3"
              >
                {material.status === "ready" ? (
                  <button
                    type="button"
                    onClick={() => handleSelectMaterial(material)}
                    className="flex min-w-0 flex-1 items-center gap-3 rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={
                      material.type === "pdf"
                        ? `Open ${material.originalName}`
                        : `Play ${material.originalName}`
                    }
                  >
                    <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium" title={material.originalName}>{material.originalName}</p>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[material.status]}`}
                        >
                          {STATUS_LABEL[material.status]}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {TYPE_LABEL[material.type]}
                        </span>
                        {formatBytes(material.sizeBytes) ? (
                          <span className="text-xs text-muted-foreground">
                            {formatBytes(material.sizeBytes)}
                          </span>
                        ) : null}
                        <span className="text-xs text-muted-foreground">
                          {formatUploadDate(material.createdAt)}
                        </span>
                      </div>
                    </div>
                  </button>
                ) : (
                  <div className="flex min-w-0 flex-1 items-center gap-3">
                    <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium" title={material.originalName}>{material.originalName}</p>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[material.status]}`}
                        >
                          {STATUS_LABEL[material.status]}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {TYPE_LABEL[material.type]}
                        </span>
                        {formatBytes(material.sizeBytes) ? (
                          <span className="text-xs text-muted-foreground">
                            {formatBytes(material.sizeBytes)}
                          </span>
                        ) : null}
                        <span className="text-xs text-muted-foreground">
                          {formatUploadDate(material.createdAt)}
                        </span>
                      </div>
                      {material.status === "failed" && material.processingError ? (
                        <p className="mt-1 text-xs text-destructive">{material.processingError}</p>
                      ) : null}
                    </div>
                  </div>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPendingDelete(material)}
                  disabled={deletingId === material.id}
                >
                  <Trash2 className="h-4 w-4" />
                  {deletingId === material.id ? "Deleting…" : "Delete"}
                </Button>
              </div>
            );
          })
        )}
      </CardContent>

      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this material?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete
                ? `"${pendingDelete.originalName}" will be permanently removed from this workspace. This cannot be undone.`
                : null}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDelete}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
}

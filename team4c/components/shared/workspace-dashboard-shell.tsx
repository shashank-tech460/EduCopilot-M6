"use client";

import { useState } from "react";

import { Card, CardHeader, CardContent, CardTitle } from "@/components/ui/card";
import { WorkspaceFiles, type MaterialSummary } from "@/components/shared/workspace-files";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { VideoPlayer } from "@/components/video/VideoPlayer";
import { TabNavigation } from "@/components/shared/TabNavigation";
import { PanelErrorBoundary } from "@/components/shared/PanelErrorBoundary";
import { useWorkspaceInit } from "@/hooks/useWorkspaceInit";
import { useAppStore } from "@/store/appStore";

interface WorkspaceDashboardShellProps {
  workspaceId: string;
  workspaceName: string;
  initialMaterials: MaterialSummary[];
  initialVideoFile: MaterialSummary | undefined;
}

const TABS = [
  { id: "video", label: "Video" },
  { id: "chat", label: "AI Tutor" },
  { id: "files", label: "Materials" },
] as const;

type TabId = (typeof TABS)[number]["id"];

/**
 * Accion Labs Requirement 1 (Interactive Learning Dashboard) — the 3-panel
 * shell. Extracted into its own client component specifically because
 * `useWorkspaceInit` (Task 1.3) is a client hook, while the parent page
 * remains a Server Component doing the actual authenticated/ownership-
 * checked data fetch (Phase 4/5 pattern, unchanged) — this wrapper is the
 * smallest boundary needed, not a conversion of the whole page.
 *
 * 1.1 — the three panels render in a responsive layout at `md:` (768px)
 *       and above (confirmed against Tailwind's actual
 *       `--breakpoint-md: 48rem` = 768px). Video and AI Tutor form the
 *       primary two-column learning area (each panel gets roughly half
 *       the row's width, not squeezed into a three-way split); Learning
 *       Materials is a full-width row below, since it's supporting
 *       content rather than a primary, equally-weighted panel.
 * 1.2 — `useWorkspaceInit(workspaceId, initialData)` is called here, with
 *       `initialData` seeded from the server-fetched workspace (the exact
 *       optimization Task 1.3 built `staleTime` for) so this doesn't
 *       trigger a redundant client-side fetch of data the server already
 *       has.
 * 1.3 — below `md:`, only the active tab's panel renders; at `md:` and
 *       above, all three always render regardless of `activeTab`, and the
 *       tab navigation itself is hidden (`md:hidden`). Visibility is
 *       controlled entirely through Tailwind's responsive display
 *       classes (`hidden md:block` / `block md:block`) — the native
 *       `hidden` HTML attribute is deliberately NOT also used here, since
 *       the two would conflict over which one wins at each breakpoint.
 * 1.4 — see components/shared/TabNavigation.tsx for the ARIA tabs pattern
 *       details.
 *
 * Requirement 1.5 (error message + retry on panel failure) is implemented
 * via PanelErrorBoundary wrapping each panel independently — see that
 * component for details. Server-side workspace data-fetch failures are
 * handled separately by the existing app/error.tsx (Next.js's route-level
 * boundary), unchanged.
 */
export function WorkspaceDashboardShell({
  workspaceId,
  workspaceName,
  initialMaterials,
  initialVideoFile,
}: WorkspaceDashboardShellProps) {
  const [activeTab, setActiveTab] = useState<TabId>("video");

  useWorkspaceInit(workspaceId, { id: workspaceId, name: workspaceName });

  // Requirement fix: clicking a ready video/YouTube item in Learning
  // Materials (components/shared/workspace-files.tsx's handleSelectMaterial)
  // calls the existing setActiveMedia() action; this is what makes that
  // selection actually change what the Video panel displays. The `.find()`
  // against `initialMaterials` — already workspace-scoped, server-verified
  // data passed down from the ownership-checked page fetch — is the
  // security-relevant part: App_Store's `activeMediaId` persists across
  // page loads (Task 1.1), so a stale id left over from a *different*
  // workspace must never be trusted directly. If it doesn't match a file
  // that's genuinely in *this* workspace's own material list, it's simply
  // not found here and safely falls through to the server-computed default
  // — never rendering a foreign file.
  const activeMediaId = useAppStore((state) => state.video.activeMediaId);
  const selectedVideoFile = initialMaterials.find(
    (file) =>
      file.id === activeMediaId &&
      (file.type === "video" || file.type === "youtube_url") &&
      file.status === "ready"
  );
  const currentVideoFile = selectedVideoFile ?? initialVideoFile;

  function panelClasses(tabId: TabId) {
    return activeTab === tabId ? "block" : "hidden md:block";
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="md:hidden">
        <TabNavigation
          tabs={TABS as unknown as { id: string; label: string }[]}
          activeTab={activeTab}
          onChange={(id) => setActiveTab(id as TabId)}
          panelIdFor={(id) => `panel-${id}`}
        />
      </div>

      <div className="flex flex-col gap-4">
        {/* Primary learning area: Video + AI Tutor side by side at md+.
            Two columns, not three sharing one row — this is the actual
            fix for Chat collapsing into an unusably narrow column: Chat
            now gets roughly half the row's width instead of ~28% of a
            three-way split. */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <div
            id="panel-video"
            role="tabpanel"
            aria-labelledby="tab-video"
            className={panelClasses("video")}
          >
            <PanelErrorBoundary panelName="Video">
              <Card className="flex flex-col md:h-full md:min-h-[500px]">
                <CardHeader>
                  <CardTitle className="truncate" title={currentVideoFile ? currentVideoFile.originalName : undefined}>
                    {currentVideoFile ? currentVideoFile.originalName : "Current Lesson"}
                  </CardTitle>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col justify-center">
                  {currentVideoFile ? (
                    <VideoPlayer
                      fileId={currentVideoFile.id}
                      type={currentVideoFile.type as "video" | "youtube_url"}
                      storageUrl={currentVideoFile.storageUrl}
                      title={currentVideoFile.originalName}
                    />
                  ) : (
                    <div className="flex flex-col items-center gap-1 py-8 text-center">
                      <p className="text-sm font-medium">No lesson video yet</p>
                      <p className="max-w-[18rem] text-sm text-muted-foreground">
                        Upload an MP4 or add a YouTube video to start learning.
                      </p>
                    </div>
                  )}
                </CardContent>
              </Card>
            </PanelErrorBoundary>
          </div>

          <div
            id="panel-chat"
            role="tabpanel"
            aria-labelledby="tab-chat"
            className={panelClasses("chat")}
          >
            <PanelErrorBoundary panelName="Chat">
              <Card className="flex h-[500px] flex-col overflow-hidden md:h-full md:min-h-[500px]">
                <CardHeader className="border-b">
                  <CardTitle>AI Tutor</CardTitle>
                </CardHeader>
                <ChatPanel workspaceId={workspaceId} />
              </Card>
            </PanelErrorBoundary>
          </div>
        </div>

        {/* Learning Materials: supporting content, full width below the
            primary Video/Chat area rather than squeezed into a third
            column. */}
        <div
          id="panel-files"
          role="tabpanel"
          aria-labelledby="tab-files"
          className={panelClasses("files")}
        >
          <PanelErrorBoundary panelName="Files">
            <WorkspaceFiles workspaceId={workspaceId} initialMaterials={initialMaterials} />
          </PanelErrorBoundary>
        </div>
      </div>
    </div>
  );
}

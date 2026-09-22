import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { WorkspaceDashboardShell } from "@/components/shared/workspace-dashboard-shell";
import { auth } from "@/lib/auth";
import { assertOwnership, OwnershipError } from "@/lib/ownership";
import { connectToDatabase } from "@/lib/mongodb";
import { FileModel } from "@/models/File";

/**
 * Enforces Phase 4's core authorization requirement: a workspace is only
 * visible to the student who owns it. `proxy.ts` already ensures the
 * visitor is authenticated at all; this page additionally verifies
 * *ownership* of this specific workspace via assertOwnership() (docs/decisions.md
 * §3/§7). A workspace that exists but belongs to someone else renders
 * exactly the same 404 as one that doesn't exist — never a distinguishing
 * "forbidden" message — so the ID space isn't probeable.
 *
 * Stays a Server Component for the authenticated/ownership-checked data
 * fetch (unchanged from Phase 4/5). The actual 3-panel Dashboard Shell
 * (Accion Labs Requirement 1) — responsive grid, mobile tab navigation,
 * and useWorkspaceInit wiring — lives in WorkspaceDashboardShell, a client
 * component, since useWorkspaceInit is a client hook. This is the
 * smallest boundary: only the panel composition is client-side, not the
 * authorization/data-fetching above it.
 */
export default async function WorkspacePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id: rawId } = await params;
  // Defensive only — assertOwnership() already rejects any malformed ID via
  // Types.ObjectId.isValid(). This guards specifically against stray
  // whitespace from manually-copied IDs (e.g. from a mongosh session),
  // which is otherwise indistinguishable from a "wrong" ID and would
  // correctly-but-confusingly 404. Does not change the ownership check
  // itself in any way.
  const id = rawId.trim();
  const session = await auth();

  // proxy.ts already redirects unauthenticated requests to /login, so
  // session should exist here — but a page must never assume a helper
  // upstream did its job; it re-checks and fails closed if not.
  if (!session?.user?.id) {
    notFound();
  }

  await connectToDatabase();

  let workspace;
  try {
    workspace = await assertOwnership(id, session.user.id);
  } catch (error) {
    if (error instanceof OwnershipError) {
      notFound();
    }
    throw error;
  }

  const files = await FileModel.find({ workspaceId: id }).sort({ createdAt: -1 });
  const initialMaterials = files.map((file) => ({
    id: file._id.toString(),
    originalName: file.originalName,
    type: file.type,
    status: file.status,
    processingError: file.processingError ?? null,
    createdAt: (file.createdAt ?? new Date()).toISOString(),
    storageUrl: file.storageUrl,
    sizeBytes: file.sizeBytes ?? null,
  }));

  // Accion Labs Step 4: the mechanism for a user to CHOOSE which video is
  // active is Source Attribution (Requirement 3) — clicking a chat
  // citation. Without one clicked yet, VideoPlayer needs a reasonable
  // default: the first ready playable video-type file in the workspace.
  const initialVideoFile = initialMaterials.find(
    (file) => (file.type === "video" || file.type === "youtube_url") && file.status === "ready"
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        {/* Phase 6J: was plain `text-sm text-muted-foreground` — legible,
            but visually indistinguishable from ordinary secondary text
            sitting right above a much bolder page heading, so it read as
            a footnote rather than a navigation control. Given the same
            pill/chip treatment already used for suggestion chips and
            other nav affordances elsewhere, so it reads as obviously
            clickable at a glance instead of blending in. */}
        <Link
          href="/dashboard"
          className="inline-flex w-fit items-center gap-1.5 rounded-full border border-border/70 bg-card/60 px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-primary/10 hover:text-brand-indigo focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
          Back to Workspaces
        </Link>
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{workspace.name}</h1>
            <p className="text-sm text-muted-foreground">Your learning workspace</p>
          </div>
          <p className="text-sm text-muted-foreground">{session.user.name ?? session.user.email}</p>
        </div>
      </div>
      <WorkspaceDashboardShell
        workspaceId={id}
        workspaceName={workspace.name}
        initialMaterials={initialMaterials}
        initialVideoFile={initialVideoFile}
      />
    </div>
  );
}

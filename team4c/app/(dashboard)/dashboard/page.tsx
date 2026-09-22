import { Types } from "mongoose";

import { auth } from "@/lib/auth";
import { connectToDatabase } from "@/lib/mongodb";
import { WorkspaceModel } from "@/models/Workspace";
import { FileModel } from "@/models/File";
import { WorkspaceDashboard } from "@/components/shared/workspace-dashboard";

/**
 * Server component: fetches the authenticated user's workspaces directly
 * (no round-trip through /api/workspaces from the server itself — that
 * route exists for the client-side create/delete flow and for any future
 * consumer, but a server component querying MongoDB directly is the more
 * efficient and idiomatic path for its own initial render). Interactive
 * behavior (create/delete) lives in the WorkspaceDashboard client component.
 *
 * Phase 6H: also aggregates each workspace's real material counts (total,
 * ready, and by type) so the premium dashboard cards can show genuine
 * data instead of a bare name — never fabricated statistics. This is a
 * Team4C-owned Mongo read against the same `files` collection every other
 * route already queries; it does not touch Team4A/Team4B/Qdrant/Redis or
 * add any new API surface.
 */
export default async function DashboardPage() {
  const session = await auth();

  await connectToDatabase();

  const workspaces = session?.user?.id
    ? await WorkspaceModel.find({ userId: session.user.id }).sort({ createdAt: -1 })
    : [];

  const workspaceIds = workspaces.map((w) => w._id as Types.ObjectId);
  const materialStats =
    workspaceIds.length > 0
      ? await FileModel.aggregate<{
          _id: Types.ObjectId;
          total: number;
          ready: number;
          pdf: number;
          video: number;
          youtube: number;
        }>([
          { $match: { workspaceId: { $in: workspaceIds } } },
          {
            $group: {
              _id: "$workspaceId",
              total: { $sum: 1 },
              ready: { $sum: { $cond: [{ $eq: ["$status", "ready"] }, 1, 0] } },
              pdf: { $sum: { $cond: [{ $eq: ["$type", "pdf"] }, 1, 0] } },
              video: { $sum: { $cond: [{ $eq: ["$type", "video"] }, 1, 0] } },
              youtube: { $sum: { $cond: [{ $eq: ["$type", "youtube_url"] }, 1, 0] } },
            },
          },
        ])
      : [];

  const statsByWorkspace = new Map(materialStats.map((s) => [s._id.toString(), s]));

  const initialWorkspaces = workspaces.map((workspace) => {
    const stats = statsByWorkspace.get(workspace._id.toString());
    return {
      id: workspace._id.toString(),
      name: workspace.name,
      createdAt: (workspace.createdAt ?? new Date()).toISOString(),
      materialCount: stats?.total ?? 0,
      readyCount: stats?.ready ?? 0,
      pdfCount: stats?.pdf ?? 0,
      videoCount: (stats?.video ?? 0) + (stats?.youtube ?? 0),
    };
  });

  return (
    <WorkspaceDashboard
      userName={session?.user?.name ?? "there"}
      initialWorkspaces={initialWorkspaces}
    />
  );
}

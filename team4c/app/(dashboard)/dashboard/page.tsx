import { auth } from "@/lib/auth";
import { connectToDatabase } from "@/lib/mongodb";
import { WorkspaceModel } from "@/models/Workspace";
import { WorkspaceDashboard } from "@/components/shared/workspace-dashboard";

/**
 * Server component: fetches the authenticated user's workspaces directly
 * (no round-trip through /api/workspaces from the server itself — that
 * route exists for the client-side create/delete flow and for any future
 * consumer, but a server component querying MongoDB directly is the more
 * efficient and idiomatic path for its own initial render). Interactive
 * behavior (create/delete) lives in the WorkspaceDashboard client component.
 */
export default async function DashboardPage() {
  const session = await auth();

  await connectToDatabase();

  const workspaces = session?.user?.id
    ? await WorkspaceModel.find({ userId: session.user.id }).sort({ createdAt: -1 })
    : [];

  const initialWorkspaces = workspaces.map((workspace) => ({
    id: workspace._id.toString(),
    name: workspace.name,
    createdAt: (workspace.createdAt ?? new Date()).toISOString(),
  }));

  return (
    <WorkspaceDashboard
      userName={session?.user?.name ?? "there"}
      initialWorkspaces={initialWorkspaces}
    />
  );
}

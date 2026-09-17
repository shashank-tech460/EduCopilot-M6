import { NextResponse } from "next/server";

import { auth } from "@/lib/auth";
import { connectToDatabase } from "@/lib/mongodb";
import { WorkspaceModel } from "@/models/Workspace";
import { validateWorkspaceName } from "@/lib/validation";

/**
 * GET /api/workspaces — the authenticated user's own workspaces only.
 *
 * The identity used for the filter comes exclusively from the verified
 * session (docs/decisions.md §3: "no route ever trusts a client-supplied
 * userId"). There is no query parameter or request body accepted here that
 * could influence which user's data gets returned.
 */
export async function GET() {
  const session = await auth();

  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  await connectToDatabase();

  const workspaces = await WorkspaceModel.find({ userId: session.user.id }).sort({
    createdAt: -1,
  });

  return NextResponse.json(
    workspaces.map((workspace) => ({
      id: workspace._id.toString(),
      name: workspace.name,
      createdAt: workspace.createdAt,
    }))
  );
}

/**
 * POST /api/workspaces — create a workspace owned by the authenticated user.
 *
 * `userId` is set from `session.user.id` only. Even if a request body
 * includes a `userId` field, it is never read — this is enforced by simply
 * never destructuring it from `body`, not by a runtime check, so there's no
 * code path that could accidentally start trusting it later.
 */
export async function POST(request: Request) {
  const session = await auth();

  if (!session?.user?.id) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  const body = await request.json().catch(() => null);
  const { valid, error } = validateWorkspaceName(body?.name);

  if (!valid) {
    return NextResponse.json({ error }, { status: 400 });
  }

  await connectToDatabase();

  const workspace = await WorkspaceModel.create({
    userId: session.user.id,
    name: String(body.name).trim(),
  });

  return NextResponse.json(
    {
      id: workspace._id.toString(),
      name: workspace.name,
      createdAt: workspace.createdAt,
    },
    { status: 201 }
  );
}

import { Sidebar } from "@/components/shared/Sidebar";
import { auth } from "@/lib/auth";

/**
 * Phase 6E application shell for the authenticated (dashboard) route
 * group. Server component so it reads the session directly via auth()
 * (same pattern as the existing SiteNav) with no flash of an empty user
 * menu on first paint; the interactive nav itself is the client Sidebar.
 */
export async function AppShell({ children }: { children: React.ReactNode }) {
  const session = await auth();
  const userName = session?.user?.name ?? session?.user?.email ?? "Account";
  const userEmail = session?.user?.email ?? "";

  return (
    <div className="flex min-h-full flex-1 flex-col md:flex-row">
      <Sidebar userName={userName} userEmail={userEmail} />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 md:px-8">{children}</main>
    </div>
  );
}

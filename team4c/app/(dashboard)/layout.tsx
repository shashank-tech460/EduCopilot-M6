import { SiteNav } from "@/components/shared/site-nav";

/**
 * Layout for the (dashboard) route group.
 * Route protection (redirecting unauthenticated users) is added in Phase 4
 * via middleware.ts, per docs/decisions.md §7. Not implemented yet.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <SiteNav />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
        {children}
      </main>
    </div>
  );
}

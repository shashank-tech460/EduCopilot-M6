import { AppShell } from "@/components/shared/AppShell";

/**
 * Layout for the (dashboard) route group.
 * Route protection (redirecting unauthenticated users) is added in Phase 4
 * via middleware.ts, per docs/decisions.md §7. Not implemented yet.
 *
 * Phase 6E: replaced the single top SiteNav with the persistent AppShell
 * (sidebar + workspace switcher on desktop, drawer on mobile) — purely a
 * navigation/visual change, no route protection or auth behavior altered.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}

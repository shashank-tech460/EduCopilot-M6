"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { GraduationCap, LayoutGrid, Menu, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { LogoutMenuItem } from "@/components/shared/logout-menu-item";
import { WorkspaceSwitcher } from "@/components/shared/WorkspaceSwitcher";

interface SidebarProps {
  userName: string;
  userEmail: string;
}

/**
 * Phase 6E application shell navigation — desktop sidebar + mobile drawer,
 * sharing one nav content definition so the two never drift apart. Replaces
 * the single top `SiteNav` for the authenticated (dashboard) route group
 * only; the public landing/auth pages keep their own header (Stage 5).
 *
 * Nav surface is deliberately minimal: "Workspaces" (the only real section
 * that exists today) plus the workspace switcher. No Settings/other link is
 * added, per the master prompt's explicit "do not expose a broken route"
 * rule — no such route exists in this product yet.
 */
export function Sidebar({ userName, userEmail }: SidebarProps) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const isWorkspacesActive = pathname === "/dashboard";

  const navContent = (
    <>
      <Link
        href="/"
        className="flex items-center gap-2 px-1 py-1 font-semibold tracking-tight transition-opacity hover:opacity-80"
      >
        <GraduationCap className="h-5 w-5 text-brand-indigo" aria-hidden="true" />
        <span className="truncate">EduCopilot</span>
      </Link>

      <nav className="mt-6 flex flex-col gap-1" aria-label="Main">
        <Link
          href="/dashboard"
          aria-current={isWorkspacesActive ? "page" : undefined}
          onClick={() => setMobileOpen(false)}
          className={cn(
            "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm font-medium transition-colors duration-[var(--duration-sm)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring",
            isWorkspacesActive
              ? "bg-sidebar-accent text-sidebar-accent-foreground"
              : "text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
          )}
        >
          <LayoutGrid className="h-4 w-4" aria-hidden="true" />
          Workspaces
        </Link>
      </nav>

      <div className="mt-4">
        <WorkspaceSwitcher />
      </div>

      <div className="mt-auto pt-4">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-2.5 rounded-md px-2 py-2 text-left transition-colors duration-[var(--duration-sm)] hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
              aria-label="Open user menu"
            >
              <Avatar className="h-8 w-8 shrink-0">
                <AvatarFallback>{userName.charAt(0).toUpperCase()}</AvatarFallback>
              </Avatar>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">{userName}</span>
                <span className="block truncate text-xs text-muted-foreground">{userEmail}</span>
              </span>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" side="top" className="w-56">
            <DropdownMenuItem asChild>
              <Link href="/dashboard">Dashboard</Link>
            </DropdownMenuItem>
            <LogoutMenuItem />
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-3 py-4 text-sidebar-foreground md:flex">
        {navContent}
      </aside>

      {/* Mobile top bar */}
      <div className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-sidebar-border bg-sidebar px-4 text-sidebar-foreground md:hidden">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <GraduationCap className="h-5 w-5 text-brand-indigo" aria-hidden="true" />
          <span>EduCopilot</span>
        </Link>
        <button
          type="button"
          onClick={() => setMobileOpen(true)}
          className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
          aria-label="Open navigation menu"
        >
          <Menu className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>

      {/* Mobile drawer */}
      <DialogPrimitive.Root open={mobileOpen} onOpenChange={setMobileOpen}>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 md:hidden" />
          <DialogPrimitive.Content
            className="fixed inset-y-0 left-0 z-50 flex h-full w-72 flex-col border-r border-sidebar-border bg-sidebar px-3 py-4 text-sidebar-foreground shadow-lg outline-none data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left duration-[var(--duration-md)] md:hidden"
            aria-describedby={undefined}
          >
            <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
            <DialogPrimitive.Close
              className="absolute right-3 top-3 flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-sidebar-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
              aria-label="Close navigation menu"
            >
              <X className="h-4 w-4" />
            </DialogPrimitive.Close>
            {navContent}
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>
    </>
  );
}

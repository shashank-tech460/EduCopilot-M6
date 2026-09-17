"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { signOut } from "next-auth/react";
import { LogOut } from "lucide-react";

import { DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { useAppStore } from "@/store/appStore";
import { toast } from "@/store/useToastStore";

/**
 * Logout menu item — deliberately its own client component rather than a
 * <form action={serverSignOut}> nested inside a Radix DropdownMenuItem.
 *
 * Root cause this fixes: Radix's DropdownMenu.Item (which underlies
 * DropdownMenuItem) manages its own selection lifecycle — on select, it
 * closes the menu and unmounts its Portal-rendered content immediately.
 * When the item's child was a <button type="submit"> inside a <form
 * action={...}> Server Action, that unmount could race with (and cut off)
 * the form's submission before the Server Action's request actually
 * completed, so `signOut()` on the server was sometimes never reached —
 * the click appeared to do nothing. Using a plain onClick handler calling
 * next-auth/react's client-side `signOut()` (the same client API already
 * used for sign-in in app/(auth)/login/page.tsx) avoids the form/Portal
 * interaction entirely: it's a normal async function call, not something
 * that depends on the DOM node it was triggered from surviving.
 */
export function LogoutMenuItem() {
  const router = useRouter();
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  async function handleLogout() {
    if (isLoggingOut) return;
    setIsLoggingOut(true);

    try {
      // Clear all in-memory (and persisted, via appStore's own
      // persist/partialize config) user-scoped state before the session
      // itself is gone, so a slow redirect can't briefly render the
      // previous user's workspace/chat/video/upload state.
      useAppStore.getState().logout();

      // `redirect: false` so we control navigation ourselves via
      // router.push, consistent with how login/signup already navigate
      // in this app, rather than letting next-auth do a raw
      // window.location redirect.
      const result = await signOut({ redirect: false, callbackUrl: "/" });

      router.push(result?.url ?? "/");
      router.refresh();
    } catch {
      toast({
        title: "Log out failed",
        description: "Something went wrong. Please try again.",
        variant: "destructive",
      });
      setIsLoggingOut(false);
    }
  }

  return (
    <DropdownMenuItem
      onSelect={(event) => {
        // Prevent Radix's default "close on select" from racing the async
        // logout work in a way that could leave state inconsistent; the
        // menu closes naturally anyway once navigation occurs.
        event.preventDefault();
        void handleLogout();
      }}
      disabled={isLoggingOut}
      className="text-destructive focus:text-destructive"
    >
      <LogOut className="h-4 w-4" />
      {isLoggingOut ? "Logging out…" : "Log out"}
    </DropdownMenuItem>
  );
}

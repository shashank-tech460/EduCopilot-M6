import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * Regression test for the logout bug: the previous inline
 * <form action={...}>{"use server"}...</form> in site-nav.tsx referenced
 * `signOut` and `LogOut` without importing them (confirmed via
 * `npm run typecheck` failing with "Cannot find name 'signOut'" / "'LogOut'"
 * before this fix), and even once that's fixed, nesting a Server-Action
 * form inside a Radix DropdownMenuItem is a known race: the menu unmounts
 * on select before the form's submission reliably completes.
 *
 * This test exercises the actual fix — LogoutMenuItem, a plain client
 * component using next-auth/react's client-side signOut() — end to end:
 * click fires signOut, clears the App_Store, and navigates away. No DOM
 * form/Server Action involved, so there's nothing for Radix to race.
 */

const signOutMock = vi.fn();
const pushMock = vi.fn();
const refreshMock = vi.fn();

vi.mock("next-auth/react", () => ({
  signOut: (...args: unknown[]) => signOutMock(...args),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, refresh: refreshMock }),
}));

import { LogoutMenuItem } from "@/components/shared/logout-menu-item";
import { DropdownMenu, DropdownMenuContent } from "@/components/ui/dropdown-menu";
import { useAppStore } from "@/store/appStore";

function renderLogoutMenuItem() {
  // DropdownMenuItem (Radix) requires a parent Menu/DropdownMenu context.
  // `open` is forced so the content actually mounts without a trigger click.
  return render(
    <DropdownMenu open>
      <DropdownMenuContent>
        <LogoutMenuItem />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function seedNonDefaultStoreState() {
  useAppStore.getState().setSession({ userId: "user-1" });
  useAppStore.getState().setWorkspace({ id: "ws-1", name: "DBMS" });
  useAppStore.getState().addMessage({
    id: "m1",
    role: "user",
    content: "hello",
    timestamp: new Date(),
    status: "complete",
  });
}

beforeEach(() => {
  signOutMock.mockReset();
  pushMock.mockReset();
  refreshMock.mockReset();
  useAppStore.getState().logout();
});

describe("LogoutMenuItem", () => {
  it("clicking Log out calls next-auth's client-side signOut with redirect disabled", async () => {
    signOutMock.mockResolvedValue({ url: "/" });
    const user = userEvent.setup();
    renderLogoutMenuItem();

    await user.click(screen.getByText("Log out"));

    expect(signOutMock).toHaveBeenCalledWith({ redirect: false, callbackUrl: "/" });
  });

  it("clears the App_Store (session, workspace, chat) before navigating away", async () => {
    seedNonDefaultStoreState();
    signOutMock.mockResolvedValue({ url: "/" });
    const user = userEvent.setup();
    renderLogoutMenuItem();

    await user.click(screen.getByText("Log out"));

    const state = useAppStore.getState();
    expect(state.session).toBeNull();
    expect(state.workspace).toBeNull();
    expect(state.chat.messages).toEqual([]);
  });

  it("redirects to the URL next-auth's signOut resolves to", async () => {
    signOutMock.mockResolvedValue({ url: "/" });
    const user = userEvent.setup();
    renderLogoutMenuItem();

    await user.click(screen.getByText("Log out"));

    expect(pushMock).toHaveBeenCalledWith("/");
    expect(refreshMock).toHaveBeenCalled();
  });

  it("disables itself while logout is in progress, preventing double-clicks", async () => {
    let resolveSignOut: (value: { url: string }) => void = () => {};
    signOutMock.mockReturnValue(
      new Promise((resolve) => {
        resolveSignOut = resolve;
      })
    );
    const user = userEvent.setup();
    renderLogoutMenuItem();

    const item = screen.getByText("Log out").closest('[role="menuitem"]');
    await user.click(screen.getByText("Log out"));

    expect(screen.getByText("Logging out…")).toBeInTheDocument();
    expect(item).toHaveAttribute("data-disabled");

    resolveSignOut({ url: "/" });
  });

  it("shows an error toast and does not navigate if signOut throws", async () => {
    signOutMock.mockRejectedValue(new Error("network error"));
    const user = userEvent.setup();
    renderLogoutMenuItem();

    await user.click(screen.getByText("Log out"));

    // Failed logout must not silently pretend to succeed.
    expect(pushMock).not.toHaveBeenCalled();
  });
});

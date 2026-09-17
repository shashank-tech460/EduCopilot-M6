import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

import { WorkspaceFiles } from "@/components/shared/workspace-files";

/**
 * Regression test for the controlled/uncontrolled input warning.
 *
 * Root cause: the "Add Material" dialog's YouTube-URL branch and
 * PDF/MP4-file branch were two conditionally-rendered subtrees at the same
 * JSX position with no distinguishing `key`. React's reconciler saw the
 * same `div > Label + Input` shape in both branches and reused a single
 * underlying `<input>` DOM node instead of unmounting one and mounting the
 * other when `activeTab` changed. Toggling to the YouTube tab added a
 * `value` prop to that reused node (uncontrolled → controlled); toggling
 * away removed it (controlled → uncontrolled) — both directions of the
 * warning, from a single root cause.
 *
 * The fix adds distinct `key`s to the two branches so React always mounts
 * a fresh DOM node per tab. This test proves it by actually switching tabs
 * in jsdom and asserting the warning is never logged — not just reasoning
 * about the fix structurally.
 */
describe("WorkspaceFiles — controlled/uncontrolled input regression", () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  function expectNoControlledUncontrolledWarning() {
    const offendingCall = consoleErrorSpy.mock.calls.find((call: unknown[]) =>
      String(call[0]).includes("A component is changing")
    );
    expect(offendingCall).toBeUndefined();
  }

  it("does not warn when switching PDF → MP4 → YouTube → PDF", async () => {
    const user = userEvent.setup();
    render(<WorkspaceFiles workspaceId="workspace-1" initialMaterials={[]} />);

    await user.click(screen.getByRole("button", { name: "Add Material" }));

    // Starts on the default "Upload PDF" tab.
    expect(screen.getByLabelText("PDF file")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Upload MP4" }));
    expect(screen.getByLabelText("MP4 file")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add YouTube URL" }));
    expect(screen.getByLabelText("YouTube URL")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Upload PDF" }));
    expect(screen.getByLabelText("PDF file")).toBeInTheDocument();

    expectNoControlledUncontrolledWarning();
  });

  it("does not warn after typing a YouTube URL, then switching away and back", async () => {
    const user = userEvent.setup();
    render(<WorkspaceFiles workspaceId="workspace-1" initialMaterials={[]} />);

    await user.click(screen.getByRole("button", { name: "Add Material" }));
    await user.click(screen.getByRole("button", { name: "Add YouTube URL" }));

    const urlInput = screen.getByLabelText("YouTube URL");
    await user.type(urlInput, "https://youtu.be/dQw4w9WgXcQ");
    expect(urlInput).toHaveValue("https://youtu.be/dQw4w9WgXcQ");

    await user.click(screen.getByRole("button", { name: "Upload PDF" }));
    await user.click(screen.getByRole("button", { name: "Add YouTube URL" }));

    // The `key` fix remounts the DOM node when switching tabs, but
    // `youtubeUrl` itself lives in WorkspaceFiles' own state (not in the
    // remounted child), so the typed value correctly survives the round
    // trip — a user who taps another tab by accident doesn't lose what
    // they typed. That's expected, desirable behavior, not a bug.
    expect(screen.getByLabelText("YouTube URL")).toHaveValue(
      "https://youtu.be/dQw4w9WgXcQ"
    );

    expectNoControlledUncontrolledWarning();
  });

  it("does not warn across many repeated tab switches", async () => {
    const user = userEvent.setup();
    render(<WorkspaceFiles workspaceId="workspace-1" initialMaterials={[]} />);

    await user.click(screen.getByRole("button", { name: "Add Material" }));

    const tabs = ["Upload MP4", "Add YouTube URL", "Upload PDF"] as const;
    for (let i = 0; i < 5; i++) {
      for (const tab of tabs) {
        await user.click(screen.getByRole("button", { name: tab }));
      }
    }

    expectNoControlledUncontrolledWarning();
  });
});

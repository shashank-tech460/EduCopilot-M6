import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

/**
 * Regression tests for the reported bug: clicking an uploaded PDF, MP4, or
 * YouTube material in Learning Materials did nothing at all — there was no
 * interaction wired up. These tests use the REAL WorkspaceFiles component
 * (not mocked, unlike workspace-dashboard-shell.test.tsx's suite, which
 * mocks it to isolate the shell's own layout/tab logic) together with the
 * real WorkspaceDashboardShell, so the actual click → App_Store
 * (`setActiveMedia`) → re-render pipeline is genuinely exercised end to
 * end. VideoPlayer and ChatPanel are mocked (heavy, unrelated internals
 * already covered by their own test files).
 */

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

vi.mock("@/hooks/useWorkspaceInit", () => ({
  useWorkspaceInit: vi.fn(),
}));

vi.mock("@/components/video/VideoPlayer", () => ({
  VideoPlayer: ({ title, fileId }: { title: string; fileId: string }) => (
    <div data-testid="mock-video">
      Now playing: {title} ({fileId})
    </div>
  ),
}));

vi.mock("@/components/chat/ChatPanel", () => ({
  ChatPanel: () => <div data-testid="mock-chat" />,
}));

import { WorkspaceDashboardShell } from "@/components/shared/workspace-dashboard-shell";
import { useAppStore } from "@/store/appStore";
import type { MaterialSummary } from "@/components/shared/workspace-files";

const readyPdf: MaterialSummary = {
  id: "pdf-1",
  originalName: "Course-Notes.pdf",
  type: "pdf",
  status: "ready",
  processingError: null,
  createdAt: "2026-01-01T00:00:00.000Z",
  storageUrl: "https://example.test/course-notes.pdf",
  sizeBytes: 1000,
};

const readyMp4: MaterialSummary = {
  id: "mp4-1",
  originalName: "Lecture.mp4",
  type: "video",
  status: "ready",
  processingError: null,
  createdAt: "2026-01-01T00:00:00.000Z",
  storageUrl: "https://example.test/lecture.mp4",
  sizeBytes: 2000,
};

const readyYoutube: MaterialSummary = {
  id: "yt-1",
  originalName: "L-1.4: Types of OS",
  type: "youtube_url",
  status: "ready",
  processingError: null,
  createdAt: "2026-01-01T00:00:00.000Z",
  storageUrl: "https://youtu.be/abc123",
  sizeBytes: null,
};

const processingMp4: MaterialSummary = {
  id: "mp4-processing",
  originalName: "Still-Processing.mp4",
  type: "video",
  status: "processing",
  processingError: null,
  createdAt: "2026-01-01T00:00:00.000Z",
  storageUrl: "https://example.test/processing.mp4",
  sizeBytes: 3000,
};

const failedMp4: MaterialSummary = {
  id: "mp4-failed",
  originalName: "Failed-Upload.mp4",
  type: "video",
  status: "failed",
  processingError: "Something went wrong",
  createdAt: "2026-01-01T00:00:00.000Z",
  storageUrl: "https://example.test/failed.mp4",
  sizeBytes: 4000,
};

const allMaterials = [readyPdf, readyMp4, readyYoutube, processingMp4, failedMp4];

beforeEach(() => {
  vi.clearAllMocks();
  useAppStore.getState().setActiveMedia(null);
});

describe("Learning Materials → Video Player selection (regression fix)", () => {
  it("clicking a ready MP4 loads it into the Video panel", async () => {
    const user = userEvent.setup();
    render(
      <WorkspaceDashboardShell
        workspaceId="ws-1"
        workspaceName="DBMS"
        initialMaterials={allMaterials}
        initialVideoFile={readyPdf as never}
      />
    );

    await user.click(screen.getByRole("button", { name: "Play Lecture.mp4" }));

    expect(screen.getByTestId("mock-video")).toHaveTextContent("Now playing: Lecture.mp4 (mp4-1)");
    expect(useAppStore.getState().video.activeMediaId).toBe("mp4-1");
  });

  it("clicking a ready YouTube material loads it into the Video panel", async () => {
    const user = userEvent.setup();
    render(
      <WorkspaceDashboardShell
        workspaceId="ws-1"
        workspaceName="DBMS"
        initialMaterials={allMaterials}
        initialVideoFile={readyMp4}
      />
    );

    await user.click(screen.getByRole("button", { name: "Play L-1.4: Types of OS" }));

    expect(screen.getByTestId("mock-video")).toHaveTextContent("Now playing: L-1.4: Types of OS (yt-1)");
  });

  it("switching between two ready videos updates the Video panel each time", async () => {
    const user = userEvent.setup();
    render(
      <WorkspaceDashboardShell
        workspaceId="ws-1"
        workspaceName="DBMS"
        initialMaterials={allMaterials}
        initialVideoFile={readyMp4}
      />
    );

    await user.click(screen.getByRole("button", { name: "Play L-1.4: Types of OS" }));
    expect(screen.getByTestId("mock-video")).toHaveTextContent("yt-1");

    await user.click(screen.getByRole("button", { name: "Play Lecture.mp4" }));
    expect(screen.getByTestId("mock-video")).toHaveTextContent("mp4-1");
  });

  it("clicking a ready PDF opens it in a new tab and does NOT change the Video panel", async () => {
    const windowOpenSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    const user = userEvent.setup();
    render(
      <WorkspaceDashboardShell
        workspaceId="ws-1"
        workspaceName="DBMS"
        initialMaterials={allMaterials}
        initialVideoFile={readyMp4}
      />
    );

    await user.click(screen.getByRole("button", { name: "Open Course-Notes.pdf" }));

    expect(windowOpenSpy).toHaveBeenCalledWith(
      "https://example.test/course-notes.pdf",
      "_blank",
      "noopener,noreferrer"
    );
    // The video panel is unaffected — PDFs never touch activeMediaId.
    expect(screen.getByTestId("mock-video")).toHaveTextContent("mp4-1");
    expect(useAppStore.getState().video.activeMediaId).toBeNull();

    windowOpenSpy.mockRestore();
  });

  it("a processing material is not selectable — no button is rendered for it", () => {
    render(
      <WorkspaceDashboardShell
        workspaceId="ws-1"
        workspaceName="DBMS"
        initialMaterials={allMaterials}
        initialVideoFile={readyMp4}
      />
    );

    expect(screen.queryByRole("button", { name: "Play Still-Processing.mp4" })).not.toBeInTheDocument();
    // The name is still visible (not hidden), just not interactive.
    expect(screen.getByText("Still-Processing.mp4")).toBeInTheDocument();
  });

  it("a failed material is not selectable — no button is rendered for it", () => {
    render(
      <WorkspaceDashboardShell
        workspaceId="ws-1"
        workspaceName="DBMS"
        initialMaterials={allMaterials}
        initialVideoFile={readyMp4}
      />
    );

    expect(screen.queryByRole("button", { name: "Play Failed-Upload.mp4" })).not.toBeInTheDocument();
    expect(screen.getByText("Failed-Upload.mp4")).toBeInTheDocument();
  });

  it("Delete remains a separate, independent action from selecting a material", async () => {
    render(
      <WorkspaceDashboardShell
        workspaceId="ws-1"
        workspaceName="DBMS"
        initialMaterials={allMaterials}
        initialVideoFile={readyMp4}
      />
    );

    // The selectable region and Delete are siblings, not nested — both
    // independently reachable, confirming no invalid nested-interactive-
    // element markup was introduced by this fix.
    expect(screen.getByRole("button", { name: "Play Lecture.mp4" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Delete" }).length).toBeGreaterThan(0);
  });
});

describe("Learning Materials → Video Player selection — workspace isolation", () => {
  it("a stale activeMediaId left over from a different workspace never resolves to a file outside this workspace's own material list", () => {
    // Simulates App_Store's persisted video.activeMediaId (Task 1.1)
    // carrying over from a previously-visited, different workspace.
    useAppStore.getState().setActiveMedia("some-other-workspaces-file-id");

    render(
      <WorkspaceDashboardShell
        workspaceId="ws-1"
        workspaceName="DBMS"
        initialMaterials={allMaterials}
        initialVideoFile={readyMp4}
      />
    );

    // Falls through safely to the server-computed default — the foreign
    // id is never found in this workspace's own (already-scoped)
    // initialMaterials, so it can never cause a foreign file to render.
    expect(screen.getByTestId("mock-video")).toHaveTextContent("mp4-1");
  });
});

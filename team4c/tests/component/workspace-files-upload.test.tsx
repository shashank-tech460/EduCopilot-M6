import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

import { WorkspaceFiles } from "@/components/shared/workspace-files";
import { useAppStore } from "@/store/appStore";
import { MAX_PDF_SIZE_BYTES, MAX_VIDEO_SIZE_BYTES } from "@/lib/validation";

/**
 * Tests the Task 6.1 upload behavior: client-side pre-validation
 * (Requirement 5.4 / Property 8) and failed-upload retry without
 * reselecting the file (Property 18). XMLHttpRequest is mocked — jsdom's
 * real implementation would attempt an actual network request.
 */

class MockXHR {
  static instances: MockXHR[] = [];
  upload = { onprogress: null as ((e: ProgressEvent) => void) | null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  status = 0;
  responseText = "";
  sentBody: FormData | null = null;

  open() {}
  send(body: FormData) {
    this.sentBody = body;
    MockXHR.instances.push(this);
  }

  respondSuccess(data: Record<string, unknown>) {
    this.status = 201;
    this.responseText = JSON.stringify(data);
    this.onload?.();
  }

  respondFailure(status: number, data: Record<string, unknown>) {
    this.status = status;
    this.responseText = JSON.stringify(data);
    this.onload?.();
  }
}

function pdfFile(name: string, sizeBytes: number): globalThis.File {
  const file = new File(["x".repeat(Math.min(sizeBytes, 10))], name, { type: "application/pdf" });
  Object.defineProperty(file, "size", { value: sizeBytes });
  return file;
}

function mp4File(name: string, sizeBytes: number): globalThis.File {
  const file = new File(["x".repeat(Math.min(sizeBytes, 10))], name, { type: "video/mp4" });
  Object.defineProperty(file, "size", { value: sizeBytes });
  return file;
}

beforeEach(() => {
  MockXHR.instances = [];
  vi.stubGlobal("XMLHttpRequest", MockXHR);
  useAppStore.getState().clearUploads();
});

describe("WorkspaceFiles — Requirement 5.4 / Property 8 (validate before initiating upload)", () => {
  it("rejects an oversized PDF client-side and never opens an XHR request", async () => {
    const user = userEvent.setup();
    render(<WorkspaceFiles workspaceId="ws-1" initialMaterials={[]} />);

    await user.click(screen.getByRole("button", { name: "Add Material" }));
    const input = screen.getByLabelText("PDF file");
    const oversized = pdfFile("huge.pdf", MAX_PDF_SIZE_BYTES + 1);
    await user.upload(input, oversized);
    await user.click(screen.getByRole("button", { name: "Add Material" }));

    expect(MockXHR.instances).toHaveLength(0);
    expect(screen.getByText("PDF must be 50MB or smaller.")).toBeInTheDocument();
  });

  it("rejects an oversized MP4 client-side and never opens an XHR request", async () => {
    const user = userEvent.setup();
    render(<WorkspaceFiles workspaceId="ws-1" initialMaterials={[]} />);

    await user.click(screen.getByRole("button", { name: "Add Material" }));
    await user.click(screen.getByRole("button", { name: "Upload MP4" }));
    const input = screen.getByLabelText("MP4 file");
    const oversized = mp4File("huge.mp4", MAX_VIDEO_SIZE_BYTES + 1);
    await user.upload(input, oversized);
    await user.click(screen.getByRole("button", { name: "Add Material" }));

    expect(MockXHR.instances).toHaveLength(0);
    expect(screen.getByText("Video must be 500MB or smaller.")).toBeInTheDocument();
  });

  it("does not initiate an upload with no file selected", async () => {
    const user = userEvent.setup();
    render(<WorkspaceFiles workspaceId="ws-1" initialMaterials={[]} />);

    await user.click(screen.getByRole("button", { name: "Add Material" }));
    await user.click(screen.getByRole("button", { name: "Add Material" }));

    expect(MockXHR.instances).toHaveLength(0);
    expect(screen.getByText("Choose a file first.")).toBeInTheDocument();
  });

  it("initiates a real upload for a valid PDF", async () => {
    const user = userEvent.setup();
    render(<WorkspaceFiles workspaceId="ws-1" initialMaterials={[]} />);

    await user.click(screen.getByRole("button", { name: "Add Material" }));
    const input = screen.getByLabelText("PDF file");
    await user.upload(input, pdfFile("notes.pdf", 1024));
    await user.click(screen.getByRole("button", { name: "Add Material" }));

    expect(MockXHR.instances).toHaveLength(1);
    expect(MockXHR.instances[0].sentBody?.get("type")).toBe("pdf");
  });
});

describe("WorkspaceFiles — Property 9 (live progress reflected in UI)", () => {
  it("shows the UploadTracker with live progress as xhr.upload.onprogress fires", async () => {
    const user = userEvent.setup();
    render(<WorkspaceFiles workspaceId="ws-1" initialMaterials={[]} />);

    await user.click(screen.getByRole("button", { name: "Add Material" }));
    await user.upload(screen.getByLabelText("PDF file"), pdfFile("notes.pdf", 1000));
    await user.click(screen.getByRole("button", { name: "Add Material" }));

    const xhr = MockXHR.instances[0];
    act(() => {
      xhr.upload.onprogress?.({ lengthComputable: true, loaded: 500, total: 1000 } as ProgressEvent);
    });

    // Property 9 requires all of: filename, percentage, progress bar, ETA.
    // Asserting only percentage (as a narrower earlier version of this
    // test did) would let a regression removing the filename, the
    // progressbar element, or the ETA text pass unnoticed.
    const tracker = await screen.findByTestId("upload-tracker");
    await waitFor(() => expect(tracker).toHaveTextContent("50%"));
    expect(tracker).toHaveTextContent("notes.pdf");
    expect(within(tracker).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
    expect(tracker.textContent).toMatch(/Calculating…|remaining|Almost done/);
  });
});

describe("WorkspaceFiles — Property 18 (failed upload retention + retry without reselecting)", () => {
  it("keeps the File reference after a failed upload and Retry re-sends the same file without reopening the picker", async () => {
    const user = userEvent.setup();
    render(<WorkspaceFiles workspaceId="ws-1" initialMaterials={[]} />);

    await user.click(screen.getByRole("button", { name: "Add Material" }));
    await user.upload(screen.getByLabelText("PDF file"), pdfFile("notes.pdf", 1000));
    await user.click(screen.getByRole("button", { name: "Add Material" }));

    // Dialog closes immediately (upload proceeds in the background,
    // tracked by UploadTracker) — the file picker is gone at this point.
    expect(screen.queryByLabelText("PDF file")).not.toBeInTheDocument();

    const firstXhr = MockXHR.instances[0];
    act(() => {
      firstXhr.respondFailure(500, { error: "Something went wrong." });
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    });

    // The original File object must still be retained in the store for
    // Retry to work without the user reselecting anything.
    const uploadId = Object.keys(useAppStore.getState().uploads)[0];
    expect(useAppStore.getState().uploads[uploadId].fileRef?.name).toBe("notes.pdf");

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(MockXHR.instances).toHaveLength(2);
    expect(MockXHR.instances[1].sentBody?.get("file")).toEqual(
      expect.objectContaining({ name: "notes.pdf" })
    );

    act(() => {
      MockXHR.instances[1].respondSuccess({
        id: "f1",
        originalName: "notes.pdf",
        type: "pdf",
        status: "uploading",
        processingError: null,
        createdAt: new Date().toISOString(),
        storageUrl: "https://example.test/notes.pdf",
        sizeBytes: 1000,
      });
    });

    await waitFor(() => {
      expect(screen.getByText("notes.pdf")).toBeInTheDocument();
      expect(screen.queryByTestId("upload-tracker")).not.toBeInTheDocument();
    });
  });
});

describe("WorkspaceFiles — Requirement 5.6 (file list metadata)", () => {
  it("displays name, type, size, upload date, and status for an existing material", () => {
    render(
      <WorkspaceFiles
        workspaceId="ws-1"
        initialMaterials={[
          {
            id: "f1",
            originalName: "Lecture12.pdf",
            type: "pdf",
            status: "ready",
            processingError: null,
            createdAt: "2026-01-15T00:00:00.000Z",
            storageUrl: "https://example.test/lecture12.pdf",
            sizeBytes: 2 * 1024 * 1024,
          },
        ]}
      />
    );

    expect(screen.getByText("Lecture12.pdf")).toBeInTheDocument();
    expect(screen.getByText("PDF")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("2.0 MB")).toBeInTheDocument();
    expect(screen.getByText("Jan 15, 2026")).toBeInTheDocument();
  });

  it("does not render a size for a YouTube URL material, which has no local bytes", () => {
    render(
      <WorkspaceFiles
        workspaceId="ws-1"
        initialMaterials={[
          {
            id: "f2",
            originalName: "https://youtu.be/dQw4w9WgXcQ",
            type: "youtube_url",
            status: "ready",
            processingError: null,
            createdAt: "2026-01-15T00:00:00.000Z",
            storageUrl: "https://youtu.be/dQw4w9WgXcQ",
            sizeBytes: null,
          },
        ]}
      />
    );

    expect(screen.getByText("YouTube")).toBeInTheDocument();
    expect(screen.queryByText(/MB|KB|B$/)).not.toBeInTheDocument();
  });
});

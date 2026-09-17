import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { UploadTracker } from "@/components/files/UploadTracker";
import type { UploadState } from "@/store/appStore";

function baseUpload(overrides: Partial<UploadState> = {}): UploadState {
  return {
    id: "u1",
    fileName: "Lecture12.pdf",
    fileType: "pdf",
    fileSize: 1024,
    uploadDate: new Date(),
    progress: 0,
    estimatedTimeRemaining: null,
    status: "uploading",
    fileRef: null,
    ...overrides,
  };
}

describe("UploadTracker — Property 9 (upload state completeness)", () => {
  it("displays the filename, percentage, and a progress bar", () => {
    render(<UploadTracker upload={baseUpload({ progress: 42 })} onRetry={vi.fn()} />);

    expect(screen.getByText("Lecture12.pdf")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "42");
  });

  it("shows 'Calculating…' before enough progress data exists for a real ETA", () => {
    render(<UploadTracker upload={baseUpload({ estimatedTimeRemaining: null })} onRetry={vi.fn()} />);
    expect(screen.getByText("Calculating…")).toBeInTheDocument();
  });

  it("shows a formatted ETA once one is available", () => {
    render(<UploadTracker upload={baseUpload({ estimatedTimeRemaining: 42 })} onRetry={vi.fn()} />);
    expect(screen.getByText(/42s remaining/)).toBeInTheDocument();
  });

  it("formats a longer ETA in minutes", () => {
    render(<UploadTracker upload={baseUpload({ estimatedTimeRemaining: 125 })} onRetry={vi.fn()} />);
    expect(screen.getByText(/3 minutes remaining/)).toBeInTheDocument();
  });

  it("shows a failed status with the error message and a Retry button instead of progress", () => {
    render(
      <UploadTracker
        upload={baseUpload({ status: "failed", error: "Network error. Please try again." })}
        onRetry={vi.fn()}
      />
    );

    expect(screen.getByText("Network error. Please try again.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("clicking Retry calls onRetry with the upload's id", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(<UploadTracker upload={baseUpload({ id: "u42", status: "failed" })} onRetry={onRetry} />);

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(onRetry).toHaveBeenCalledWith("u42");
  });
});

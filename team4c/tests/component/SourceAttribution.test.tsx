import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SourceAttribution } from "@/components/chat/SourceAttribution";
import { useAppStore } from "@/store/appStore";
import type { SourceAttribution as SourceAttributionType } from "@/store/appStore";

const videoAttribution: SourceAttributionType = {
  type: "video_timestamp",
  sourceFile: "Lecture12.mp4",
  fileId: "file-1",
  location: 155,
  label: "Lecture12.mp4 at 155s",
};

const pdfAttribution: SourceAttributionType = {
  type: "pdf_page",
  sourceFile: "Course-Notes.pdf",
  fileId: "file-2",
  location: 12,
  label: "Course-Notes.pdf, page 12",
  fileUrl: "https://example.test/course-notes.pdf",
};

const unavailableAttribution: SourceAttributionType = {
  type: "video_timestamp",
  sourceFile: "Deleted.mp4",
  fileId: "file-missing",
  location: 42,
  label: "Deleted.mp4 at 42s",
  disabled: true,
};

beforeEach(() => {
  useAppStore.getState().logout();
});

describe("SourceAttribution — Property 4 (attribution rendering completeness)", () => {
  it("renders source type icon, filename, and formatted timestamp for a video attribution", () => {
    render(<SourceAttribution attribution={videoAttribution} />);

    const element = screen.getByRole("button");
    expect(element).toHaveTextContent("Lecture12.mp4");
    expect(element).toHaveTextContent("2:35"); // 155 seconds formatted
  });

  it("renders source type icon, filename, and page number for a PDF attribution", () => {
    render(<SourceAttribution attribution={pdfAttribution} />);

    const element = screen.getByRole("button");
    expect(element).toHaveTextContent("Course-Notes.pdf");
    expect(element).toHaveTextContent("Page 12");
  });
});

describe("SourceAttribution — Property 5 (timestamp seek round-trip)", () => {
  it("clicking a video attribution invokes the existing setVideoTimestamp seek mechanism with the correct value", async () => {
    const user = userEvent.setup();
    render(<SourceAttribution attribution={videoAttribution} />);

    await user.click(screen.getByRole("button"));

    expect(useAppStore.getState().video.currentTimestamp).toBe(155);
  });

  it("is keyboard activatable (real button semantics, not a div onClick)", async () => {
    const user = userEvent.setup();
    render(<SourceAttribution attribution={videoAttribution} />);

    await user.tab();
    expect(screen.getByRole("button")).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(useAppStore.getState().video.currentTimestamp).toBe(155);
  });

  it("does not introduce a feedback loop — clicking twice with the same timestamp is a stable no-op on the second click", async () => {
    const user = userEvent.setup();
    render(<SourceAttribution attribution={videoAttribution} />);

    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("button"));

    expect(useAppStore.getState().video.currentTimestamp).toBe(155);
  });
});

describe("SourceAttribution — Property 7 (missing source attribution)", () => {
  it("renders a disabled, non-interactive element with an unavailable tooltip when the source is missing from the workspace", () => {
    render(<SourceAttribution attribution={unavailableAttribution} />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    const element = screen.getByText(/Deleted\.mp4/);
    expect(element).toHaveAttribute("aria-disabled", "true");
    expect(element).toHaveAttribute("title", expect.stringMatching(/unavailable/i));
  });

  it("clicking a disabled attribution does not seek the video", async () => {
    const user = userEvent.setup();
    render(<SourceAttribution attribution={unavailableAttribution} />);

    const element = screen.getByText(/Deleted\.mp4/);
    await user.click(element);

    expect(useAppStore.getState().video.currentTimestamp).toBe(0);
  });
});

describe("SourceAttribution — PDF navigation (Requirement 3.3)", () => {
  it("opens the file URL with a #page= fragment when a valid PDF attribution is clicked", async () => {
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    const user = userEvent.setup();
    render(<SourceAttribution attribution={pdfAttribution} />);

    await user.click(screen.getByRole("button"));

    expect(openSpy).toHaveBeenCalledWith(
      "https://example.test/course-notes.pdf#page=12",
      "_blank",
      "noopener,noreferrer"
    );
    openSpy.mockRestore();
  });
});

describe("SourceAttribution — visual distinction (Requirement 3.4)", () => {
  it("renders valid and disabled attributions with different visual treatment", () => {
    const { rerender } = render(<SourceAttribution attribution={videoAttribution} />);
    const validElement = screen.getByRole("button");
    expect(validElement.className).toMatch(/underline/);
    expect(validElement.className).not.toMatch(/opacity-60/);

    rerender(<SourceAttribution attribution={unavailableAttribution} />);
    const disabledElement = screen.getByText(/Deleted\.mp4/);
    expect(disabledElement.className).toMatch(/opacity-60/);
  });
});

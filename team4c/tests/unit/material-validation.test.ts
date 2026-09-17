import { describe, expect, it } from "vitest";

import {
  validateYoutubeUrl,
  validateUploadedFile,
  MAX_PDF_SIZE_BYTES,
  MAX_VIDEO_SIZE_BYTES,
} from "@/lib/validation";

describe("validateYoutubeUrl", () => {
  it("accepts a standard youtube.com/watch?v= URL", () => {
    expect(validateYoutubeUrl("https://www.youtube.com/watch?v=dQw4w9WgXcQ").valid).toBe(true);
  });

  it("accepts a youtube.com URL without www", () => {
    expect(validateYoutubeUrl("https://youtube.com/watch?v=dQw4w9WgXcQ").valid).toBe(true);
  });

  it("accepts a youtu.be short URL", () => {
    expect(validateYoutubeUrl("https://youtu.be/dQw4w9WgXcQ").valid).toBe(true);
  });

  it("accepts a youtu.be short URL with a playlist query parameter (regression)", () => {
    // Reproduces the reported bug exactly: a youtu.be link's query string
    // starts with "?", not "&" — the regex's trailing group previously only
    // permitted "&", so this shape was incorrectly rejected.
    expect(
      validateYoutubeUrl(
        "https://youtu.be/kBdIM6hNDAE?list=PLxCzCOWd7aiFAN6I8CuViBuCdJ"
      ).valid
    ).toBe(true);
  });

  it("accepts a youtu.be short URL with a timestamp query parameter", () => {
    expect(validateYoutubeUrl("https://youtu.be/dQw4w9WgXcQ?t=42").valid).toBe(true);
  });

  it("accepts a youtube.com URL with extra query params", () => {
    expect(validateYoutubeUrl("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s").valid).toBe(
      true
    );
  });

  it("rejects an empty URL", () => {
    const result = validateYoutubeUrl("");
    expect(result.valid).toBe(false);
    expect(result.error).toBeDefined();
  });

  it("rejects an arbitrary non-YouTube URL", () => {
    const result = validateYoutubeUrl("https://example.com/video");
    expect(result.valid).toBe(false);
    expect(result.error).toBeDefined();
  });

  it("rejects a YouTube channel/playlist URL (not a single video)", () => {
    const result = validateYoutubeUrl("https://www.youtube.com/channel/UC1234567890");
    expect(result.valid).toBe(false);
  });

  it("rejects a non-string value", () => {
    expect(validateYoutubeUrl(undefined).valid).toBe(false);
  });
});

describe("validateUploadedFile — PDF", () => {
  it("accepts a valid PDF by MIME type", () => {
    const result = validateUploadedFile(
      { name: "lecture.pdf", type: "application/pdf", size: 1024 },
      "pdf"
    );
    expect(result.valid).toBe(true);
  });

  it("accepts a PDF by extension when MIME type is missing", () => {
    const result = validateUploadedFile({ name: "lecture.pdf", type: "", size: 1024 }, "pdf");
    expect(result.valid).toBe(true);
  });

  it("rejects a non-PDF file for the pdf slot", () => {
    const result = validateUploadedFile(
      { name: "notes.docx", type: "application/msword", size: 1024 },
      "pdf"
    );
    expect(result.valid).toBe(false);
  });

  it("rejects a PDF larger than the size cap", () => {
    const result = validateUploadedFile(
      { name: "huge.pdf", type: "application/pdf", size: MAX_PDF_SIZE_BYTES + 1 },
      "pdf"
    );
    expect(result.valid).toBe(false);
  });
});

describe("validateUploadedFile — video", () => {
  it("accepts a valid MP4 by MIME type", () => {
    const result = validateUploadedFile(
      { name: "lecture12.mp4", type: "video/mp4", size: 1024 },
      "video"
    );
    expect(result.valid).toBe(true);
  });

  it("rejects a non-MP4 video format", () => {
    const result = validateUploadedFile(
      { name: "lecture12.mov", type: "video/quicktime", size: 1024 },
      "video"
    );
    expect(result.valid).toBe(false);
  });

  it("rejects a video larger than the size cap", () => {
    const result = validateUploadedFile(
      { name: "huge.mp4", type: "video/mp4", size: MAX_VIDEO_SIZE_BYTES + 1 },
      "video"
    );
    expect(result.valid).toBe(false);
  });

  it("rejects a missing file", () => {
    expect(validateUploadedFile(null, "video").valid).toBe(false);
    expect(validateUploadedFile(undefined, "pdf").valid).toBe(false);
  });
});

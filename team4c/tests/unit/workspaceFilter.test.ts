import { describe, expect, it } from "vitest";

import { filterWorkspaceReferences } from "@/lib/workspaceFilter";
import type { SourceAttribution } from "@/store/appStore";

function citation(fileId: string, disabled = false): SourceAttribution {
  return {
    type: "video_timestamp",
    sourceFile: "Lecture.mp4",
    fileId,
    location: 100,
    label: "0:01:40",
    disabled,
  };
}

describe("filterWorkspaceReferences", () => {
  it("leaves a citation enabled when its fileId belongs to the active workspace", () => {
    const result = filterWorkspaceReferences([citation("file-1")], ["file-1", "file-2"]);
    expect(result[0].disabled).toBe(false);
  });

  it("disables a citation whose fileId does not belong to the active workspace", () => {
    const result = filterWorkspaceReferences([citation("file-outside-workspace")], [
      "file-1",
      "file-2",
    ]);
    expect(result[0].disabled).toBe(true);
  });

  it("does not re-enable a citation that was already explicitly disabled", () => {
    const result = filterWorkspaceReferences([citation("file-1", true)], ["file-1"]);
    expect(result[0].disabled).toBe(true);
  });

  it("handles an empty workspace file list by disabling every citation", () => {
    const result = filterWorkspaceReferences([citation("file-1"), citation("file-2")], []);
    expect(result.every((attribution) => attribution.disabled)).toBe(true);
  });

  it("does not mutate the input array", () => {
    const input = [citation("file-1")];
    filterWorkspaceReferences(input, []);
    expect(input[0].disabled).toBe(false);
  });

  it("preserves every other field on the citation unchanged", () => {
    const result = filterWorkspaceReferences([citation("file-1")], ["file-1"]);
    expect(result[0]).toMatchObject({
      type: "video_timestamp",
      sourceFile: "Lecture.mp4",
      fileId: "file-1",
      location: 100,
      label: "0:01:40",
    });
  });
});

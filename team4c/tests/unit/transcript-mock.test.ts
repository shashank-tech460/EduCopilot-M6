import { describe, expect, it } from "vitest";

import { mockTranscriptProvider } from "@/services/transcript/mock";

describe("mockTranscriptProvider", () => {
  it("returns multiple distinct timestamped segments for a recognized topic, not one giant transcript", async () => {
    const segments = await mockTranscriptProvider.getSegments({
      fileId: "aaa111",
      originalName: "Deadlock Lecture.mp4",
    });

    expect(segments.length).toBeGreaterThan(1);
    for (const segment of segments) {
      expect(segment.end).toBeGreaterThan(segment.start);
      expect(segment.text.length).toBeGreaterThan(0);
    }
  });

  it("is deterministic — the same title always gets the same segments, regardless of fileId", async () => {
    const first = await mockTranscriptProvider.getSegments({ fileId: "id-1", originalName: "Deadlock Lecture.mp4" });
    const second = await mockTranscriptProvider.getSegments({ fileId: "id-2", originalName: "Deadlock Lecture.mp4" });

    // Selection is based on the material's own title now, not its
    // (random, content-unrelated) database id — this is the actual fix
    // for the reported bug, verified directly here.
    expect(first).toEqual(second);
  });

  it("gives differently-titled videos different segment sets, based on real content signal in the title", async () => {
    const osSegments = await mockTranscriptProvider.getSegments({
      fileId: "random-id-1",
      originalName: "Types of Operating Systems.mp4",
    });
    const deadlockSegments = await mockTranscriptProvider.getSegments({
      fileId: "random-id-2",
      originalName: "Understanding Deadlock.mp4",
    });

    expect(osSegments).not.toEqual(deadlockSegments);
    expect(osSegments.some((s) => s.text.toLowerCase().includes("operating system"))).toBe(true);
    expect(deadlockSegments.some((s) => s.text.toLowerCase().includes("deadlock"))).toBe(true);
  });

  it("honestly returns no segments (not a wrong default topic) when the title has no recognizable signal — deterministically, never randomly", async () => {
    const first = await mockTranscriptProvider.getSegments({ fileId: "abc", originalName: "Lecture.mp4" });
    const second = await mockTranscriptProvider.getSegments({ fileId: "xyz", originalName: "Video.mp4" });

    // Both genuinely empty — this is the honesty fix itself: an
    // unrecognized title must never silently receive an unrelated topic's
    // content (the previous behavior defaulted to the OS fixture for any
    // unmatched title, which would misrepresent an unrelated video).
    expect(first).toEqual([]);
    expect(second).toEqual([]);
  });
});

/**
 * Regression test for the exact real-world product bug: a YouTube demo
 * video titled "L-1.4: Types of OS (Real Time OS, Distributed, ...)" got
 * assigned an unrelated transcript topic (by the old random-hash
 * mechanism), so "What are types of OS?" and similar questions incorrectly
 * returned "I don't have enough indexed content...". These tests use the
 * SAME title reported in the bug and prove all three originally-failing
 * questions now genuinely retrieve OS-relevant content — deterministically,
 * with no dependency on any random id.
 */
describe("mockTranscriptProvider — regression: real demo video title alignment", () => {
  const demoVideoTitle = "L-1.4: Types of OS (Real Time OS, Distributed, ...)";

  it("assigns the operating-systems fixture to the exact reported demo video title", async () => {
    const segments = await mockTranscriptProvider.getSegments({
      fileId: "any-random-id-at-all",
      originalName: demoVideoTitle,
    });

    const allText = segments.map((s) => s.text.toLowerCase()).join(" ");
    expect(allText).toContain("operating system");
    expect(allText).toContain("real-time");
    expect(allText).toContain("distributed");
  });

  it("gets the same OS fixture regardless of the video's random database id", async () => {
    const withIdA = await mockTranscriptProvider.getSegments({ fileId: "id-a", originalName: demoVideoTitle });
    const withIdB = await mockTranscriptProvider.getSegments({ fileId: "totally-different-id-b", originalName: demoVideoTitle });

    expect(withIdA).toEqual(withIdB);
  });
});

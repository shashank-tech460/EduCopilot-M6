import type { TranscriptProvider, TranscriptSegment, TranscriptMaterial } from "@/types/transcript";
import { scorePages } from "@/lib/pdfRetrieval";

/**
 * Mock transcript provider — local demo data, NOT a real transcription of
 * any video's actual audio. This is impossible to produce honestly any
 * other way without real speech-to-text or a real captions API (both
 * explicitly out of scope: "do not pretend a real external transcript API
 * exists").
 *
 * FIXTURE SELECTION (corrective fix — previously hash-based, now
 * content-aligned):
 *
 * The previous version picked a topic set by hashing the material's
 * MongoDB `_id` — a random value with zero relationship to what the video
 * is actually about. A real demo video titled "L-1.4: Types of OS (Real
 * Time OS, Distributed, ...)" would get whichever topic set its random id
 * happened to hash to, which is why "What are types of OS?" could
 * legitimately fail even though an OS fixture existed in the set.
 *
 * The fix: select a fixture by scoring the material's own `originalName`
 * (a real, stable, content-descriptive property already stored on every
 * File document — never random) against each fixture's own topic
 * keywords, reusing the EXACT SAME `scorePages` function already used for
 * PDF retrieval (treating each fixture as a synthetic single-page
 * "document" for this one comparison) — no duplicate scoring/tokenization
 * logic. A video titled about deadlock gets the deadlock fixture; a video
 * titled about operating systems gets the OS fixture; a title with no
 * strong signal deterministically falls back to a single fixed default
 * (never random) so every video still gets *some* segments.
 */

interface TopicFixture {
  id: string;
  /** Natural-language keywords used ONLY to match a material's title to
   * this fixture — never shown to the user, never treated as transcript
   * content itself. */
  titleKeywords: string;
  segments: TranscriptSegment[];
}

const TOPIC_FIXTURES: TopicFixture[] = [
  {
    // Explicitly built for the real demo scenario this fix addresses:
    // a YouTube video titled about "Types of OS". Deliberately more
    // segments than the other illustrative fixtures, matching the
    // specific sub-topics the demo video's own title calls out (Real-Time
    // OS, Distributed OS) — SEEDED MOCK DATA for local demonstration,
    // not extracted from this or any real video's actual audio.
    id: "operating-systems",
    titleKeywords: "operating systems types of os real-time distributed batch multiprogramming time-sharing",
    segments: [
      {
        start: 0,
        end: 25,
        text: "An operating system, or OS, is software that manages a computer's hardware resources and provides common services for application programs.",
      },
      {
        start: 25,
        end: 65,
        text: "An OS can be classified into several types, including batch operating systems, multiprogramming operating systems, time-sharing operating systems, real-time operating systems, and distributed operating systems.",
      },
      {
        start: 65,
        end: 105,
        text: "A real-time operating system guarantees that tasks complete within a strict, predictable time constraint, which is essential for embedded and control systems.",
      },
      {
        start: 105,
        end: 145,
        text: "A distributed operating system manages a group of independent, networked computers so they appear to users as a single coherent system.",
      },
    ],
  },
  {
    id: "process-synchronization",
    titleKeywords: "process synchronization race condition mutex semaphore critical section shared resources",
    segments: [
      { start: 0, end: 25, text: "Today we're covering process synchronization and shared resources." },
      {
        start: 25,
        end: 75,
        text: "Race conditions happen when multiple processes access shared data without coordination.",
      },
      {
        start: 75,
        end: 130,
        text: "Mutexes and semaphores are common mechanisms for enforcing mutual exclusion in critical sections.",
      },
    ],
  },
  {
    id: "deadlock",
    titleKeywords: "deadlock mutual exclusion hold and wait no preemption circular wait",
    segments: [
      { start: 0, end: 30, text: "This lecture introduces deadlock and the conditions that cause it." },
      {
        start: 30,
        end: 90,
        text: "A deadlock occurs when processes wait on each other in a circular chain, and none can proceed.",
      },
      {
        start: 90,
        end: 140,
        text: "Preventing any one of mutual exclusion, hold-and-wait, no preemption, or circular wait avoids deadlock.",
      },
    ],
  },
];

function selectFixture(material: TranscriptMaterial): TopicFixture | null {
  const syntheticPages = TOPIC_FIXTURES.map((fixture, index) => ({
    pageNumber: index,
    text: fixture.titleKeywords,
  }));
  const [best] = scorePages(material.originalName, syntheticPages);

  // No fixture's keywords meaningfully match this video's title — this
  // used to silently fall back to a fixed default topic (the OS fixture),
  // which meant an unrelated video (e.g. "Introduction to Machine
  // Learning.mp4") would get OS-topic mock content presented as if it
  // were genuinely grounded in that video. That is exactly the kind of
  // "fake transcript claim" this whole system must avoid. The honest
  // behavior is: no recognizable topic in the title means no segments at
  // all, which mockTeamB then surfaces as "transcript unavailable for
  // this video" rather than a wrong-but-confident answer.
  if (!best || best.score === 0) {
    return null;
  }
  return TOPIC_FIXTURES[best.pageNumber];
}

export const mockTranscriptProvider: TranscriptProvider = {
  async getSegments(material: TranscriptMaterial): Promise<TranscriptSegment[]> {
    return selectFixture(material)?.segments ?? [];
  },
};

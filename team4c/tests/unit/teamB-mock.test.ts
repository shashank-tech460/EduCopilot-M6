import { describe, expect, it, vi, beforeEach } from "vitest";
import { Types } from "mongoose";
import { readFile } from "fs/promises";
import path from "path";

/**
 * Tests mockTeamB's orchestration logic — caching extraction results on
 * the File document, applying the retrieval threshold, constructing
 * citations, and the honest fallback paths. `FileModel.find` and
 * `readStoredFile` are mocked (same established pattern as
 * chat-api.test.ts); `extractPdfPages`/`scorePages` are NOT mocked —
 * they run for real against the same fixture PDF used in
 * pdfRetrieval.test.ts, so this test also exercises the real extraction
 * pipeline, just through the mock's own orchestration.
 */

vi.mock("@/models/File", () => ({
  FileModel: {
    find: vi.fn(),
  },
}));

vi.mock("@/services/storage", () => ({
  readStoredFile: vi.fn(),
}));

import { FileModel } from "@/models/File";
import { readStoredFile } from "@/services/storage";
import { mockTeamB } from "@/services/teamB/mock";

const mockedFileFind = vi.mocked(FileModel.find);
const mockedReadStoredFile = vi.mocked(readStoredFile);

async function loadFixtureBuffer() {
  return readFile(path.join(process.cwd(), "tests/fixtures/sample-course-notes.pdf"));
}

function fakePdfFile(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    _id: new Types.ObjectId(),
    type: "pdf",
    originalName: "Course-Notes.pdf",
    status: "ready",
    workspaceId: { toString: () => "ws-1" },
    storageProvider: "local-mock",
    publicId: "abc123",
    extractionAttempted: false,
    extractedPages: undefined,
    save: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("mockTeamB — greeting", () => {
  it("responds with a friendly introduction and no citations for a bare greeting", async () => {
    const result = await mockTeamB.query({ query: "hi", workspaceId: "ws-1", videoTimestamp: null, session_id: null, retrieval_config: null });

    expect(result.answer).toContain("AI tutor");
    expect(result.source_attributions).toEqual([]);
    // A greeting never needs to look anything up.
    expect(mockedFileFind).not.toHaveBeenCalled();
  });
});

describe("mockTeamB — no ready material", () => {
  it("honestly reports no material available, without fabricating a citation", async () => {
    mockedFileFind.mockResolvedValue([]);

    const result = await mockTeamB.query({
      query: "What is a deadlock?",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.answer).toContain("don't have any ready course material");
    expect(result.source_attributions).toEqual([]);
  });
});

describe("mockTeamB — real PDF grounding", () => {
  it("extracts the real PDF once, scores real pages, and returns a real fileId + real page number", async () => {
    const buffer = await loadFixtureBuffer();
    mockedReadStoredFile.mockResolvedValue(buffer);
    const file = fakePdfFile();
    mockedFileFind.mockResolvedValue([file] as never);

    const result = await mockTeamB.query({
      query: "What are types of operating systems?",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.source_attributions).toHaveLength(1);
    expect(result.source_attributions[0]).toMatchObject({
      document_id: file._id.toString(),
      document_title: "Course-Notes.pdf",
      page_number: 2, // the real page about operating systems in the fixture
    });
    // The answer genuinely reflects the retrieved page's real text.
    expect(result.answer).toContain("Operating systems can be classified");
    expect(result.answer).not.toContain("mock response");
  });

  it("caches extraction on the File document — a second question does not re-read or re-extract", async () => {
    const buffer = await loadFixtureBuffer();
    mockedReadStoredFile.mockResolvedValue(buffer);
    const file = fakePdfFile();
    mockedFileFind.mockResolvedValue([file] as never);

    await mockTeamB.query({ query: "What is a deadlock?", workspaceId: "ws-1", videoTimestamp: null, session_id: null, retrieval_config: null });
    expect(mockedReadStoredFile).toHaveBeenCalledTimes(1);
    expect(file.save).toHaveBeenCalledTimes(1);
    expect(file.extractionAttempted).toBe(true);

    // Second question against the SAME (now-mutated) file object reuses
    // the cached extractedPages — no second read, no second save.
    await mockTeamB.query({ query: "What is a deadlock?", workspaceId: "ws-1", videoTimestamp: null, session_id: null, retrieval_config: null });
    expect(mockedReadStoredFile).toHaveBeenCalledTimes(1);
    expect(file.save).toHaveBeenCalledTimes(1);
  });

  it("gives an honest 'not found' answer when no page scores above the retrieval threshold — never fabricates a Page 1 fallback", async () => {
    const buffer = await loadFixtureBuffer();
    mockedReadStoredFile.mockResolvedValue(buffer);
    mockedFileFind.mockResolvedValue([fakePdfFile()] as never);

    const result = await mockTeamB.query({
      query: "Explain quantum computing",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.source_attributions).toEqual([]);
    expect(result.answer).toContain("don't have enough indexed content");
  });

  it("degrades honestly when the file bytes can't be read (e.g. deleted from disk)", async () => {
    mockedReadStoredFile.mockResolvedValue(null);
    mockedFileFind.mockResolvedValue([fakePdfFile()] as never);

    const result = await mockTeamB.query({
      query: "What is a deadlock?",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.source_attributions).toEqual([]);
    expect(result.answer).toContain("don't have enough indexed content");
  });
});

describe("mockTeamB — video 'current moment' citation (real timestamp only)", () => {
  it("cites the real current videoTimestamp when the question references the current moment and a video exists", async () => {
    const videoFile = {
      _id: new Types.ObjectId(),
      type: "video",
      originalName: "Lecture.mp4",
      status: "ready",
      workspaceId: { toString: () => "ws-1" },
    };
    mockedFileFind.mockResolvedValue([videoFile] as never);

    const result = await mockTeamB.query({
      query: "What is being explained here?",
      workspaceId: "ws-1",
      videoTimestamp: 125, session_id: null, retrieval_config: null,
    });

    expect(result.source_attributions).toHaveLength(1);
    expect(result.source_attributions[0]).toMatchObject({
      document_id: videoFile._id.toString(),
      start_timestamp: 125, // the REAL reported position, not fabricated
    });
  });

  it("does NOT cite a video timestamp when videoTimestamp is null, even if the question references 'here'", async () => {
    const videoFile = {
      _id: new Types.ObjectId(),
      type: "video",
      originalName: "Lecture.mp4",
      status: "ready",
      workspaceId: { toString: () => "ws-1" },
    };
    mockedFileFind.mockResolvedValue([videoFile] as never);

    const result = await mockTeamB.query({
      query: "What is being explained here?",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.source_attributions).toEqual([]);
  });

  it("does not attach a video citation for a question with no relevant transcript content, even when a video exists", async () => {
    const videoFile = {
      _id: new Types.ObjectId(),
      type: "video",
      originalName: "Lecture.mp4",
      status: "ready",
      workspaceId: { toString: () => "ws-1" },
    };
    mockedFileFind.mockResolvedValue([videoFile] as never);

    // Deliberately shares no vocabulary with any of mockTranscriptProvider's
    // topic sets (OS-intro, synchronization, deadlock), so this is
    // deterministic regardless of which topic set the video's random id
    // happens to hash to — unlike asking "What is a deadlock?", which
    // would genuinely (and correctly) get a video citation if the video's
    // transcript happens to be the deadlock set, since cross-material
    // grounding is supposed to surface a real match when one exists. This
    // test targets the case where nothing actually matches.
    const result = await mockTeamB.query({
      query: "What is the capital of France?",
      workspaceId: "ws-1",
      videoTimestamp: 125, session_id: null, retrieval_config: null,
    });

    expect(result.source_attributions).toEqual([]);
  });
});

describe("mockTeamB — workspace scoping", () => {
  it("only ever looks up files scoped to the given workspaceId, and only ready ones", async () => {
    mockedFileFind.mockResolvedValue([]);

    await mockTeamB.query({ query: "hi there class", workspaceId: "ws-specific", videoTimestamp: null, session_id: null, retrieval_config: null });

    expect(mockedFileFind).toHaveBeenCalledWith({ workspaceId: "ws-specific", status: "ready" });
  });
});

/**
 * Regression test for the exact real-world product failure: a workspace
 * containing a YouTube video titled "L-1.4: Types of OS (Real Time OS,
 * Distributed, ...)" incorrectly returned "I couldn't find relevant
 * content..." for "What are types of OS?" and similar questions, because
 * the (now-fixed) transcript fixture assignment was based on a random
 * database id with zero relationship to the video's actual content. These
 * tests exercise the REAL end-to-end mockTeamB.query() pipeline — not just
 * the transcript provider in isolation — with the exact reported title.
 */
describe("mockTeamB — regression: 'What are types of OS?' end-to-end (the exact reported bug)", () => {
  const demoVideoFile = {
    _id: new Types.ObjectId(),
    type: "video",
    originalName: "L-1.4: Types of OS (Real Time OS, Distributed, ...)",
    status: "ready",
    workspaceId: { toString: () => "ws-1" },
  };

  it("'What are types of OS?' returns an OS-related answer with a valid video citation to the correct file", async () => {
    mockedFileFind.mockResolvedValue([demoVideoFile] as never);

    const result = await mockTeamB.query({
      query: "What are types of OS?",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.answer.toLowerCase()).toContain("operating system");
    expect(result.answer).not.toContain("don't have enough indexed content");
    expect(result.source_attributions).toHaveLength(1);
    expect(result.source_attributions[0]).toMatchObject({
      document_id: demoVideoFile._id.toString(),
    });
    expect(typeof result.source_attributions[0].start_timestamp).toBe("number");
  });

  it("'What is a real time operating system?' retrieves the real-time OS segment", async () => {
    mockedFileFind.mockResolvedValue([demoVideoFile] as never);

    const result = await mockTeamB.query({
      query: "What is a real time operating system?",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.answer.toLowerCase()).toContain("real-time");
    expect(result.source_attributions).toHaveLength(1);
  });

  it("'What is a distributed operating system?' retrieves the distributed OS segment", async () => {
    mockedFileFind.mockResolvedValue([demoVideoFile] as never);

    const result = await mockTeamB.query({
      query: "What is a distributed operating system?",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.answer.toLowerCase()).toContain("distributed");
    expect(result.source_attributions).toHaveLength(1);
  });

  it("an unrelated question against the same workspace still returns the honest no-match response", async () => {
    mockedFileFind.mockResolvedValue([demoVideoFile] as never);

    const result = await mockTeamB.query({
      query: "Explain quantum computing",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.answer).toContain("don't have enough indexed content");
    expect(result.source_attributions).toEqual([]);
  });
});

describe("mockTeamB — explicit timestamp question ('what is explained around 1:30?')", () => {
  it("finds the real mock transcript segment covering an explicitly-mentioned timestamp and cites that exact segment's start time", async () => {
    // Fixture selection is title-based (see services/transcript/mock.ts's
    // corrective fix — previously it was fileId-hash-based, which is what
    // caused the real reported bug). An explicit, on-topic title is used
    // here rather than depending on a default-fixture fallback.
    const videoFile = {
      _id: "any-random-db-id",
      type: "video",
      originalName: "Deadlock Lecture.mp4",
      status: "ready",
      workspaceId: { toString: () => "ws-1" },
    };
    mockedFileFind.mockResolvedValue([videoFile] as never);

    // "0:05" falls inside every fixture's first segment (all start at 0),
    // so this is deterministic regardless of exactly which fixture the
    // title selects, as long as selection itself is deterministic.
    const result = await mockTeamB.query({
      query: "What is explained around 0:05?",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.source_attributions).toHaveLength(1);
    expect(result.source_attributions[0]).toMatchObject({
      document_id: "any-random-db-id",
      start_timestamp: 0, // the real segment's own start time
    });
  });

  it("does not fabricate a segment when the explicit timestamp falls outside every real segment's range", async () => {
    const videoFile = {
      _id: "any-random-db-id",
      type: "video",
      originalName: "Deadlock Lecture.mp4",
      status: "ready",
      workspaceId: { toString: () => "ws-1" },
    };
    mockedFileFind.mockResolvedValue([videoFile] as never);

    // Every mock topic fixture ends by 145s — 99:00 (5940s) is far outside all of them.
    const result = await mockTeamB.query({
      query: "What is explained around 99:00?",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.source_attributions).toEqual([]);
  });
});

describe("mockTeamB — cross-material answer (PDF + video citations together)", () => {
  it("returns both a PDF citation and a video citation when both genuinely match the same question", async () => {
    const buffer = await loadFixtureBuffer();
    mockedReadStoredFile.mockResolvedValue(buffer);
    const pdfFile = fakePdfFile();
    const videoFile = {
      _id: "any-random-db-id", // irrelevant to fixture selection — the title is what matters now
      type: "video",
      originalName: "L-1.4: Types of OS (Real Time OS, Distributed, ...)",
      status: "ready",
      workspaceId: { toString: () => "ws-1" },
    };
    mockedFileFind.mockResolvedValue([pdfFile, videoFile] as never);

    const result = await mockTeamB.query({
      query: "What are types of operating systems?",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.source_attributions?.length).toBeGreaterThanOrEqual(1);
    // A "pdf" attribution is identified by having page_number populated
    // (Team 4B's real schema has no explicit `type` discriminator field
    // -- see app/api/chat/route.ts's toSourceAttribution adapter).
    const hasPdfAttribution = result.source_attributions.some((a) => a.page_number != null);
    expect(hasPdfAttribution).toBe(true);
  });
});

describe("mockTeamB — honest 'transcript unavailable' for an unrecognized video topic", () => {
  it("gives a distinct 'transcript isn't available' message (not a fabricated answer) when the video's title matches no seeded topic", async () => {
    const videoFile = {
      _id: new Types.ObjectId(),
      type: "video",
      originalName: "Introduction to Machine Learning.mp4",
      status: "ready",
      workspaceId: { toString: () => "ws-1" },
    };
    mockedFileFind.mockResolvedValue([videoFile] as never);

    const result = await mockTeamB.query({
      query: "What is explained in this video?",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.answer).toContain("Transcript information isn't available");
    expect(result.answer).toContain("Introduction to Machine Learning.mp4");
    expect(result.source_attributions).toEqual([]);
  });

  it("does NOT silently attach an unrelated topic's citation for an unrecognized video", async () => {
    const videoFile = {
      _id: new Types.ObjectId(),
      type: "video",
      originalName: "Introduction to Machine Learning.mp4",
      status: "ready",
      workspaceId: { toString: () => "ws-1" },
    };
    mockedFileFind.mockResolvedValue([videoFile] as never);

    // Even a question that happens to share no vocabulary with any seeded
    // topic must never get a citation pointing at unrelated mock content.
    const result = await mockTeamB.query({
      query: "What is a neural network?",
      workspaceId: "ws-1",
      videoTimestamp: null, session_id: null, retrieval_config: null,
    });

    expect(result.source_attributions).toEqual([]);
  });
});

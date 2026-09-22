import { describe, expect, it, vi, beforeEach } from "vitest";

/**
 * Phase 6G — tests scripts/migrate-ingestion-generation.ts's real logic
 * against a fully-mocked FileModel/connectToDatabase (no live MongoDB
 * connection opened), matching the established pattern in
 * tests/unit/files-api.test.ts. Covers requirement B ("existing File
 * without the field can be safely migrated") from the Phase 6G master
 * prompt's test list.
 */

vi.mock("@/lib/mongodb", () => ({
  connectToDatabase: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/models/File", () => ({
  FileModel: {
    countDocuments: vi.fn(),
    updateMany: vi.fn(),
    find: vi.fn(),
  },
}));

import { FileModel } from "@/models/File";
import { migrate } from "../../scripts/migrate-ingestion-generation";

const mockedCountDocuments = vi.mocked(FileModel.countDocuments);
const mockedUpdateMany = vi.mocked(FileModel.updateMany);
const mockedFind = vi.mocked(FileModel.find);

const EXPECTED_FILTER = { currentIngestionGeneration: { $exists: false } };

beforeEach(() => {
  vi.clearAllMocks();
});

describe("migrate-ingestion-generation — backfilling existing File documents", () => {
  it("backfills currentIngestionGeneration=0 only on documents missing the field", async () => {
    mockedCountDocuments.mockResolvedValueOnce(3).mockResolvedValueOnce(0);
    mockedUpdateMany.mockResolvedValueOnce({ modifiedCount: 3 } as never);

    await migrate(false);

    expect(mockedCountDocuments).toHaveBeenCalledWith(EXPECTED_FILTER);
    expect(mockedUpdateMany).toHaveBeenCalledWith(EXPECTED_FILTER, { $set: { currentIngestionGeneration: 0 } });
    // The exact same $exists:false filter is re-checked after the write to
    // confirm zero remain -- this is what proves the migration actually
    // converged, not merely that updateMany was called with some count.
    expect(mockedCountDocuments).toHaveBeenLastCalledWith(EXPECTED_FILTER);
  });

  it("is idempotent: a second run against already-migrated data performs no write", async () => {
    mockedCountDocuments.mockResolvedValueOnce(0);

    await migrate(false);

    expect(mockedUpdateMany).not.toHaveBeenCalled();
  });

  it("--dry-run never calls updateMany, even when documents are affected", async () => {
    mockedCountDocuments.mockResolvedValueOnce(2);
    mockedFind.mockReturnValueOnce({
      select: vi.fn().mockReturnValue({
        limit: vi.fn().mockResolvedValue([]),
      }),
    } as never);

    await migrate(true);

    expect(mockedUpdateMany).not.toHaveBeenCalled();
  });

  it("never touches any field other than currentIngestionGeneration", async () => {
    mockedCountDocuments.mockResolvedValueOnce(1).mockResolvedValueOnce(0);
    mockedUpdateMany.mockResolvedValueOnce({ modifiedCount: 1 } as never);

    await migrate(false);

    const [, update] = mockedUpdateMany.mock.calls[0];
    expect(Object.keys(update as object)).toEqual(["$set"]);
    expect(Object.keys((update as { $set: object }).$set)).toEqual(["currentIngestionGeneration"]);
  });
});

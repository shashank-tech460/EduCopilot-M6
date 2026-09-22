/**
 * Phase 6G — backfills `currentIngestionGeneration` onto File documents
 * that predate the field (models/File.ts's Rev.4.4 Phase 1 schema
 * addition — a Mongoose `default: 0` only applies at document-creation
 * time, never retroactively to already-persisted documents).
 *
 * Team 4A's `MongoAuthorityClient.claim()` (team4a/app/pipeline/mongo_authority.py)
 * requires this field to exist for its `{"currentIngestionGeneration":
 * {"$lte": generation}}` compare-and-swap filter to ever match — a
 * genuinely-absent field never satisfies `$lte`, so every real canonical
 * ingestion attempt against a File document missing this field
 * deterministically fails with `aborted_authority_lost` (confirmed live,
 * see docs/PHASE_6_LIVE_COLLECTION_ALIGNMENT.md §9).
 *
 * Safety properties:
 *   - Idempotent: the `$exists: false` filter means a second run matches
 *     zero documents and is a no-op — safe to run as many times as needed.
 *   - Narrow: touches ONLY documents that genuinely lack the field. Never
 *     overwrites a value Team 4A (or anything else) has already set —
 *     `$exists: false` cannot match a document that already has any
 *     value for this field, including `0` itself.
 *   - Conservative initial value: backfills exactly `0`, the same value
 *     Mongoose's own schema default already applies to every new File
 *     document — this is not a new convention invented for the
 *     migration, it's the existing one applied retroactively. `0` is
 *     `<=` every real generation Team 4A's Redis-issued counter can ever
 *     produce (`INCR` starts counting from 1), so a freshly-backfilled
 *     File can always accept its first real ingestion's authority claim.
 *   - Explicit and inspectable: run manually via `npx tsx
 *     scripts/migrate-ingestion-generation.ts`, never wired into app
 *     startup or any request path — a deliberate, one-time, auditable
 *     operation, not an automatic reactive migration.
 *   - No other field is touched, no document's `status`/`processingError`/
 *     anything else is modified — this migration is scoped to exactly
 *     the one field Team 4A's authority claim reads.
 *
 * Usage:
 *   npx tsx scripts/migrate-ingestion-generation.ts        (apply)
 *   npx tsx scripts/migrate-ingestion-generation.ts --dry-run  (report only, no writes)
 */
import "dotenv/config";

import { connectToDatabase } from "../lib/mongodb";
import { FileModel } from "../models/File";

const DRY_RUN = process.argv.includes("--dry-run");

/** Exported so tests/unit/migrate-ingestion-generation.test.ts can exercise
 * the real migration logic against a fully-mocked FileModel/connectToDatabase
 * (same pattern as tests/unit/files-api.test.ts), without opening a live
 * MongoDB connection. */
export async function migrate(dryRun: boolean) {
  await connectToDatabase();

  const filter = { currentIngestionGeneration: { $exists: false } };
  const affectedCount = await FileModel.countDocuments(filter);

  console.log(`Files missing currentIngestionGeneration: ${affectedCount}`);

  if (affectedCount === 0) {
    console.log("Nothing to migrate — already up to date.");
    return;
  }

  if (dryRun) {
    const sample = await FileModel.find(filter).select("_id originalName workspaceId status createdAt").limit(10);
    console.log("--dry-run: no writes performed. Sample of affected documents:");
    for (const file of sample) {
      console.log(
        `  ${file._id.toString()}  workspace=${file.workspaceId.toString()}  status=${file.status}  ${file.originalName}`
      );
    }
    if (affectedCount > sample.length) {
      console.log(`  ... and ${affectedCount - sample.length} more`);
    }
    return;
  }

  const result = await FileModel.updateMany(filter, { $set: { currentIngestionGeneration: 0 } });
  console.log(`Backfilled currentIngestionGeneration=0 on ${result.modifiedCount} File document(s).`);

  const remaining = await FileModel.countDocuments(filter);
  console.log(`Remaining files missing the field: ${remaining} (expect 0).`);
}

/* c8 ignore start -- CLI entry point, exercised manually, not under test */
if (require.main === module) {
  migrate(DRY_RUN)
    .then(() => process.exit(0))
    .catch((error) => {
      console.error("Migration failed:", error);
      process.exit(1);
    });
}
/* c8 ignore stop */

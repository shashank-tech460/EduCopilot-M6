import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // Phase 6D finding: full (unbounded) local parallelism caused a real,
  // reproduced flake in auth-workspace.spec.ts's session-redirect check
  // ONLY when running the full suite alongside this project's real,
  // CPU-heavy RAG E2E tests (core-rag/youtube-rag/source-isolation,
  // each driving real local Ollama inference) -- confirmed by re-running
  // the exact same failing test in isolation and in smaller batches,
  // where it passed reliably every time. Root cause: this project's real
  // backend (one local Next.js server process, one local Ollama
  // instance) cannot serve 8 concurrent heavy real-service tests
  // reliably on one development machine, regardless of which tests are
  // running -- a genuine environment/resource-contention issue, not a
  // security or session-logic defect (separately confirmed: 82/82
  // dedicated ownership/auth/JWT/citation-filtering unit tests pass).
  workers: process.env.CI ? 1 : 3,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run build && npm run start",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});

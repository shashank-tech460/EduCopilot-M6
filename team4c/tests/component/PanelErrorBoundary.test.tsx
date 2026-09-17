import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PanelErrorBoundary } from "@/components/shared/PanelErrorBoundary";

/**
 * A deliberately failing test component. `shouldThrow` is read once per
 * mount (via a module-level flag the test controls), so Retry — which
 * remounts this component via PanelErrorBoundary's key-based reset — can
 * actually recover once the test flips the flag, proving Retry gives the
 * component "another opportunity to render," not just a no-op.
 */
let shouldThrow = true;
function Bomb() {
  if (shouldThrow) {
    throw new Error("Deliberate test failure");
  }
  return <p>Recovered content</p>;
}

function FilesStub() {
  return <p>Files content</p>;
}
function VideoStub() {
  return <p>Video content</p>;
}

beforeEach(() => {
  shouldThrow = true;
});

describe("PanelErrorBoundary — Test 1: catches the error and shows fallback UI", () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // React itself also logs caught errors to console.error in dev mode —
    // suppressing that noise here so the test's own assertion (below) can
    // cleanly check for OUR specific log call without unrelated matches.
    consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  it("shows the error UI instead of the crashed content, with a Retry button", () => {
    render(
      <PanelErrorBoundary panelName="Chat">
        <Bomb />
      </PanelErrorBoundary>
    );

    expect(screen.queryByText("Recovered content")).not.toBeInTheDocument();
    expect(
      screen.getByText("Something went wrong while loading this panel.")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

describe("PanelErrorBoundary — Test 2: error is actually logged to the console", () => {
  it("calls console.error with the real error when the panel throws", () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <PanelErrorBoundary panelName="Chat">
        <Bomb />
      </PanelErrorBoundary>
    );

    const loggedOurError = consoleErrorSpy.mock.calls.some((call) =>
      call.some(
        (arg) =>
          (typeof arg === "string" && arg.includes("[Chat panel] render error")) ||
          (arg instanceof Error && arg.message === "Deliberate test failure")
      )
    );
    expect(loggedOurError).toBe(true);

    consoleErrorSpy.mockRestore();
  });
});

describe("PanelErrorBoundary — Test 3: Retry gives the panel another chance to render", () => {
  it("clicking Retry remounts the panel, which can then succeed", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const user = userEvent.setup();

    render(
      <PanelErrorBoundary panelName="Chat">
        <Bomb />
      </PanelErrorBoundary>
    );

    expect(
      screen.getByText("Something went wrong while loading this panel.")
    ).toBeInTheDocument();

    // Simulate the underlying problem being resolved (e.g. a transient
    // issue) before the user retries.
    shouldThrow = false;
    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(screen.getByText("Recovered content")).toBeInTheDocument();
    expect(
      screen.queryByText("Something went wrong while loading this panel.")
    ).not.toBeInTheDocument();

    vi.restoreAllMocks();
  });
});

describe("PanelErrorBoundary — Test 4: panel isolation", () => {
  it("only the crashed panel shows the error UI; sibling panels keep rendering normally", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <div>
        <PanelErrorBoundary panelName="Files">
          <FilesStub />
        </PanelErrorBoundary>
        <PanelErrorBoundary panelName="Video">
          <VideoStub />
        </PanelErrorBoundary>
        <PanelErrorBoundary panelName="Chat">
          <Bomb />
        </PanelErrorBoundary>
      </div>
    );

    // Chat crashed and shows its own error UI...
    expect(
      screen.getByText("Something went wrong while loading this panel.")
    ).toBeInTheDocument();
    // ...but Files and Video are completely unaffected, independent subtrees.
    expect(screen.getByText("Files content")).toBeInTheDocument();
    expect(screen.getByText("Video content")).toBeInTheDocument();

    vi.restoreAllMocks();
  });
});

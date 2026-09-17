import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/hooks/useSourceScope", () => ({
  useSourceScope: vi.fn(),
}));

import { useSourceScope } from "@/hooks/useSourceScope";
import { SourceScopePicker } from "@/components/chat/SourceScopePicker";

const mockedUseSourceScope = vi.mocked(useSourceScope);

interface TestSource {
  id: string;
  originalName: string;
  type: "pdf" | "video" | "youtube_url";
  status: "uploading" | "processing" | "ready" | "failed";
}

const READY_SOURCES: TestSource[] = [
  { id: "doc-A", originalName: "Operating Systems.pdf", type: "pdf", status: "ready" },
  { id: "doc-B", originalName: "Lecture.mp4", type: "video", status: "ready" },
  { id: "doc-C", originalName: "Networking.pdf", type: "pdf", status: "ready" },
];

afterEach(() => {
  vi.clearAllMocks();
});

function mockScope(selectedDocumentIds: string[] | null, sources: TestSource[] = READY_SOURCES) {
  mockedUseSourceScope.mockReturnValue({
    sources,
    readySources: sources.filter((s) => s.status === "ready"),
    isLoadingSources: false,
    selectedDocumentIds,
    updateScope: vi.fn(),
  });
}

describe("SourceScopePicker — label states after hydration (MVP M6 correction)", () => {
  it("null → 'Using all workspace materials'", () => {
    mockScope(null);
    render(<SourceScopePicker workspaceId="ws-1" conversationId="conv-1" />);
    expect(screen.getByText("Using all workspace materials")).toBeInTheDocument();
  });

  it("one hydrated document_id → 'Using: <filename>' -- never the raw ID", () => {
    mockScope(["doc-A"]);
    render(<SourceScopePicker workspaceId="ws-1" conversationId="conv-1" />);
    expect(screen.getByText("Using: Operating Systems.pdf")).toBeInTheDocument();
    expect(screen.queryByText(/doc-A/)).not.toBeInTheDocument();
  });

  it("multiple hydrated document_ids → 'Using N selected sources'", () => {
    mockScope(["doc-A", "doc-B"]);
    render(<SourceScopePicker workspaceId="ws-1" conversationId="conv-1" />);
    expect(screen.getByText("Using 2 selected sources")).toBeInTheDocument();
  });

  it("explicit empty scope → 'No sources selected', never 'all workspace materials'", () => {
    mockScope([]);
    render(<SourceScopePicker workspaceId="ws-1" conversationId="conv-1" />);
    expect(screen.getByText("No sources selected")).toBeInTheDocument();
    expect(screen.queryByText("Using all workspace materials")).not.toBeInTheDocument();
  });

  it("a hydrated selection whose document is no longer ready is shown as invalidated, not as still active", () => {
    mockScope(["doc-A"], [
      { ...READY_SOURCES[0], status: "failed" },
      READY_SOURCES[1],
      READY_SOURCES[2],
    ]);
    render(<SourceScopePicker workspaceId="ws-1" conversationId="conv-1" />);
    expect(screen.getByText("No sources selected")).toBeInTheDocument();
    expect(screen.getByText("Selected source is no longer available.")).toBeInTheDocument();
  });
});

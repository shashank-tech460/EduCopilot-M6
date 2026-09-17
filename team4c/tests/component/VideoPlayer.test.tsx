import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

/**
 * Tests VideoPlayer against the real Requirement 4 acceptance criteria,
 * with video.js itself mocked (jsdom has no real media/video APIs for it
 * to attach to). The mock captures event handlers exactly as the real
 * video.js API shape does (`player.on(event, cb)`), so firing them here
 * exercises VideoPlayer's actual handler logic, not just confirms
 * `videojs()` was called.
 */

const handlers: Record<string, () => void> = {};
let currentTimeValue = 0;

const mockPlayer = {
  on: vi.fn((event: string, cb: () => void) => {
    handlers[event] = cb;
  }),
  currentTime: vi.fn((seconds?: number) => {
    if (seconds !== undefined) {
      currentTimeValue = seconds;
      return undefined;
    }
    return currentTimeValue;
  }),
  duration: vi.fn(() => 2745),
  error: vi.fn(() => ({ message: "Network error" })),
  play: vi.fn(),
  dispose: vi.fn(),
};

const videojsMock = vi.fn<(element: unknown, options: Record<string, unknown>) => typeof mockPlayer>(
  () => mockPlayer
);

vi.mock("video.js", () => ({
  default: (element: unknown, options: Record<string, unknown>) => videojsMock(element, options),
}));
vi.mock("video.js/dist/video-js.css", () => ({}));
vi.mock("videojs-youtube", () => ({}));

import { VideoPlayer } from "@/components/video/VideoPlayer";
import { useAppStore } from "@/store/appStore";

beforeEach(() => {
  vi.clearAllMocks();
  Object.keys(handlers).forEach((key) => delete handlers[key]);
  currentTimeValue = 0;
  useAppStore.getState().logout();
});

describe("VideoPlayer — Requirement 4.1 (MP4 and YouTube sources)", () => {
  it("configures video.js with an MP4 source and html5-only techOrder for a video file", () => {
    render(
      <VideoPlayer fileId="file-1" type="video" storageUrl="https://example.test/lecture.mp4" title="Lecture" />
    );

    const options = videojsMock.mock.calls[0][1];
    expect(options.techOrder).toEqual(["html5"]);
    expect(options.sources).toEqual([{ src: "https://example.test/lecture.mp4", type: "video/mp4" }]);
  });

  it("configures video.js with a youtube tech and youtube source type for a youtube_url file", () => {
    render(
      <VideoPlayer fileId="file-2" type="youtube_url" storageUrl="https://youtu.be/abc123" title="Lecture" />
    );

    const options = videojsMock.mock.calls[0][1];
    expect(options.techOrder).toEqual(["youtube", "html5"]);
    expect(options.sources).toEqual([{ src: "https://youtu.be/abc123", type: "video/youtube" }]);
  });
});

describe("VideoPlayer — Requirement 4.3 / 4.4 (timestamp updates to App_Store)", () => {
  it("updates the App_Store timestamp on native timeupdate", () => {
    render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);

    currentTimeValue = 42;
    act(() => {
      handlers.timeupdate();
    });

    expect(useAppStore.getState().video.currentTimestamp).toBe(42);
  });

  it("updates the App_Store timestamp on manual seek (seeked event) — Requirement 4.4", () => {
    render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);

    currentTimeValue = 900;
    act(() => {
      handlers.seeked();
    });

    expect(useAppStore.getState().video.currentTimestamp).toBe(900);
  });

  it("updates the App_Store duration on loadedmetadata", () => {
    render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);

    act(() => {
      handlers.loadedmetadata();
    });

    expect(useAppStore.getState().video.duration).toBe(2745);
  });

  it("updates isPlaying on play/pause events", () => {
    render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);

    act(() => {
      handlers.play();
    });
    expect(useAppStore.getState().video.isPlaying).toBe(true);

    act(() => {
      handlers.pause();
    });
    expect(useAppStore.getState().video.isPlaying).toBe(false);
  });
});

describe("VideoPlayer — Requirement 4.2 (seek command round-trip, Property 5)", () => {
  it("seeks and auto-plays when the App_Store timestamp changes externally (simulating a future Source Attribution click)", () => {
    render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);

    act(() => {
      useAppStore.getState().setVideoTimestamp(1935);
    });

    expect(mockPlayer.currentTime).toHaveBeenCalledWith(1935);
    expect(mockPlayer.play).toHaveBeenCalled();
  });

  it("does NOT re-seek in response to its own timeupdate echo (no feedback loop)", () => {
    render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);

    currentTimeValue = 100;
    act(() => {
      handlers.timeupdate();
    });

    // Our own timeupdate wrote 100 to the store; the subscription should
    // recognize this as its own echo (within the threshold), not treat it
    // as an incoming seek command that would call currentTime()/play()
    // again on top of the native player's own position.
    expect(mockPlayer.play).not.toHaveBeenCalled();
  });
});

describe("VideoPlayer — Requirement 4.5 (playback speed 0.5x–2x)", () => {
  it("configures playbackRates including both 0.5 and 2", () => {
    render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);

    const options = videojsMock.mock.calls[0][1];
    const rates = options.playbackRates as number[];
    expect(rates).toContain(0.5);
    expect(rates).toContain(2);
  });

  it("enables standard controls", () => {
    render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);
    const options = videojsMock.mock.calls[0][1];
    expect(options.controls).toBe(true);
  });
});

describe("VideoPlayer — Requirement 4.6 (error overlay on load failure)", () => {
  it("shows an error overlay with the failure reason when video.js reports an error", () => {
    render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);

    act(() => {
      handlers.error();
    });

    expect(screen.getByText("Network error")).toBeInTheDocument();
  });

  it("falls back to a generic message when video.js provides no error message", () => {
    mockPlayer.error.mockReturnValueOnce(null as never);
    render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);

    act(() => {
      handlers.error();
    });

    expect(
      screen.getByText(/could not be loaded.*re-upload.*check the URL/i)
    ).toBeInTheDocument();
  });
});

describe("VideoPlayer — App_Store activeMediaId sync", () => {
  it("sets activeMediaId to the given fileId on mount", () => {
    render(<VideoPlayer fileId="file-42" type="video" storageUrl="url" title="Lecture" />);
    expect(useAppStore.getState().video.activeMediaId).toBe("file-42");
  });
});

describe("VideoPlayer — cleanup", () => {
  it("disposes the video.js player on unmount", () => {
    const { unmount } = render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);
    unmount();
    expect(mockPlayer.dispose).toHaveBeenCalled();
  });
});

/**
 * Regression tests for the "VIDEOJS: WARN: The element supplied is not
 * included in the DOM" bug.
 *
 * Root cause: the previous implementation called `videojs(videoRef.current,
 * ...)` directly on a React-managed <video> ref. `player.dispose()` in the
 * cleanup function tears down/detaches that same DOM node (video.js's own
 * documented teardown behavior). Since nothing gave React a reason to
 * create a genuinely new <video> element between effect re-runs (no key
 * change, same tree position), a second `videojs()` call — from React
 * Strict Mode's dev-mode double-invoke of effects on mount, or from a real
 * navigation to a different file — always reused the same node the
 * *previous* dispose() had already detached.
 *
 * The fix: a stable wrapper <div> that React owns (never touched by
 * video.js's dispose), with a freshly `document.createElement`'d <video>
 * element created inside the effect on every single run. These tests
 * verify the actual DOM lifecycle behavior that prevents the warning —
 * not merely that the warning string doesn't appear in a log.
 */
describe("VideoPlayer — detached DOM element regression (VIDEOJS WARN fix)", () => {
  it("initializes video.js with an element that is genuinely attached to the DOM", () => {
    render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);

    const element = videojsMock.mock.calls[0][0] as Node;
    // This is the exact check video.js's own internal warning is based on —
    // testing it directly proves the fix, not just that videojs() ran.
    expect(document.body.contains(element)).toBe(true);
  });

  it("simulated React Strict Mode double-invoke (mount → cleanup → mount again) gives each init call a fresh, currently-attached element", () => {
    // Strict Mode's dev-mode behavior: run the effect, immediately run its
    // cleanup, then run the effect again — all before the next paint.
    // Simulated here via mount/unmount/mount rather than relying on
    // StrictMode actually being enabled in the test renderer.
    const first = render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);
    const firstElement = videojsMock.mock.calls[0][0] as Node;
    first.unmount();

    render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);
    const secondElement = videojsMock.mock.calls[1][0] as Node;

    // The critical assertion: NOT the same element reference reused after
    // being torn down, and the second one is genuinely still attached.
    expect(secondElement).not.toBe(firstElement);
    expect(document.body.contains(secondElement)).toBe(true);
  });

  it("changing the media source disposes the old player and initializes a fresh, attached element (not the disposed one)", () => {
    const { rerender } = render(
      <VideoPlayer fileId="file-1" type="video" storageUrl="https://example.test/a.mp4" title="A" />
    );
    const firstElement = videojsMock.mock.calls[0][0] as Node;
    expect(mockPlayer.dispose).not.toHaveBeenCalled();

    rerender(<VideoPlayer fileId="file-2" type="video" storageUrl="https://example.test/b.mp4" title="B" />);

    expect(mockPlayer.dispose).toHaveBeenCalledTimes(1);
    const secondElement = videojsMock.mock.calls[1][0] as Node;
    expect(secondElement).not.toBe(firstElement);
    expect(document.body.contains(secondElement)).toBe(true);
  });

  it("switching workspace/media (different fileId) does not initialize against a stale/detached element", () => {
    const { rerender } = render(
      <VideoPlayer fileId="workspace-a-file" type="video" storageUrl="url-a" title="A" />
    );
    rerender(<VideoPlayer fileId="workspace-b-file" type="youtube_url" storageUrl="url-b" title="B" />);

    const latestElement = videojsMock.mock.calls[videojsMock.mock.calls.length - 1][0] as Node;
    expect(document.body.contains(latestElement)).toBe(true);
    expect(useAppStore.getState().video.activeMediaId).toBe("workspace-b-file");
  });

  it("does not create duplicate/leaked player instances across a remount", () => {
    const first = render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);
    first.unmount();
    render(<VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />);

    // Exactly one dispose per init that was cleaned up: 1 unmount so far
    // happened once, meaning exactly 1 dispose call, and exactly 2 init
    // calls (initial mount + remount) — never more inits than the number
    // of (mounts), and every mount that unmounted was disposed.
    expect(videojsMock).toHaveBeenCalledTimes(2);
    expect(mockPlayer.dispose).toHaveBeenCalledTimes(1);
  });

  it("appends the freshly created video element into the stable, always-present container div", () => {
    const { container } = render(
      <VideoPlayer fileId="file-1" type="video" storageUrl="url" title="Lecture" />
    );

    const wrapper = screen.getByTestId("video-player-container");
    const element = videojsMock.mock.calls[0][0] as Node;
    expect(wrapper.contains(element)).toBe(true);
    expect(container.querySelector('[data-testid="video-player-container"]')).toBe(wrapper);
  });
});

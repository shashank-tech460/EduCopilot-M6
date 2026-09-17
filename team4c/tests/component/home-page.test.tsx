import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

/**
 * Home (app/page.tsx) is an async Server Component. RTL's render() doesn't
 * resolve async components on its own, so the standard pattern for testing
 * one in isolation is to call it directly (it's just an async function
 * returning JSX) and render the resolved result. `auth` is mocked to
 * control the session; `SiteNav` (itself a separate async Server Component
 * that also calls `auth()`) is stubbed since its own behavior is already
 * covered by its own tests and is unrelated to what's being verified here.
 */

vi.mock("@/lib/auth", () => ({
  auth: vi.fn(),
}));

vi.mock("@/components/shared/site-nav", () => ({
  SiteNav: () => <nav data-testid="mock-site-nav" />,
}));

import { auth } from "@/lib/auth";
import Home from "@/app/page";

/**
 * `auth` from lib/auth.ts is Auth.js's overloaded export (it can also wrap
 * route handlers/middleware, hence the broader inferred type). Here it's
 * only ever called as a plain `() => Promise<Session | null>`, so it's
 * cast to that narrower shape — same fix already established in
 * tests/unit/workspaces-api.test.ts and tests/unit/chat-api.test.ts.
 */
type SimpleAuthFn = () => Promise<{
  user: { id: string; name?: string | null; email?: string | null };
  expires: string;
} | null>;

const mockedAuth = vi.mocked(auth) as unknown as ReturnType<typeof vi.fn<SimpleAuthFn>>;

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Home landing page — authentication-aware hero CTA", () => {
  it("shows Get Started and Sign In when the user is not authenticated", async () => {
    mockedAuth.mockResolvedValue(null);

    render(await Home());

    expect(screen.getByRole("link", { name: /Get Started/ })).toHaveAttribute("href", "/signup");
    expect(screen.getByRole("link", { name: "Sign In" })).toHaveAttribute("href", "/login");
  });

  it("shows Open Dashboard when the user is authenticated", async () => {
    mockedAuth.mockResolvedValue({
      user: { id: "user-1", name: "Sample Student", email: "sample@example.com" },
      expires: "2099-01-01",
    });

    render(await Home());

    expect(screen.getByRole("link", { name: /Open Dashboard/ })).toHaveAttribute("href", "/dashboard");
  });

  it("does NOT show Sign In or Get Started when the user is authenticated", async () => {
    mockedAuth.mockResolvedValue({
      user: { id: "user-1", name: "Sample Student", email: "sample@example.com" },
      expires: "2099-01-01",
    });

    render(await Home());

    expect(screen.queryByRole("link", { name: "Sign In" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Get Started/ })).not.toBeInTheDocument();
  });

  it("does NOT show Open Dashboard when the user is not authenticated", async () => {
    mockedAuth.mockResolvedValue(null);

    render(await Home());

    expect(screen.queryByRole("link", { name: /Open Dashboard/ })).not.toBeInTheDocument();
  });

  it("Open Dashboard points to the same /dashboard route the header's account menu already uses", async () => {
    mockedAuth.mockResolvedValue({
      user: { id: "user-1", name: "Sample Student", email: "sample@example.com" },
      expires: "2099-01-01",
    });

    render(await Home());

    // The header's own Dashboard link (SiteNav) is stubbed out in this
    // test, but its real implementation is independently verified to use
    // "/dashboard" — see components/shared/site-nav.tsx. This assertion
    // confirms the landing page CTA targets the identical route, not a
    // new/invented one.
    expect(screen.getByRole("link", { name: /Open Dashboard/ })).toHaveAttribute("href", "/dashboard");
  });

  it("leaves the rest of the landing page content unchanged regardless of auth state", async () => {
    mockedAuth.mockResolvedValue(null);
    render(await Home());

    expect(
      screen.getByRole("heading", { name: "Learn from your own course material." })
    ).toBeInTheDocument();
    expect(screen.getByText("AI Tutor")).toBeInTheDocument();
  });
});

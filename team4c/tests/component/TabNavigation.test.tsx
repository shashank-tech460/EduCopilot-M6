import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TabNavigation } from "@/components/shared/TabNavigation";

const tabs = [
  { id: "a", label: "Tab A" },
  { id: "b", label: "Tab B" },
  { id: "c", label: "Tab C" },
];

describe("TabNavigation", () => {
  it("renders a tablist with one tab per item", () => {
    render(<TabNavigation tabs={tabs} activeTab="a" onChange={vi.fn()} panelIdFor={(id) => `panel-${id}`} />);
    expect(screen.getByRole("tablist")).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
  });

  it("calls onChange with the clicked tab's id", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<TabNavigation tabs={tabs} activeTab="a" onChange={onChange} panelIdFor={(id) => `panel-${id}`} />);

    await user.click(screen.getByRole("tab", { name: "Tab B" }));

    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("End key moves selection to the last tab", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<TabNavigation tabs={tabs} activeTab="a" onChange={onChange} panelIdFor={(id) => `panel-${id}`} />);

    screen.getByRole("tab", { name: "Tab A" }).focus();
    await user.keyboard("{End}");

    expect(onChange).toHaveBeenCalledWith("c");
  });

  it("ArrowLeft from the first tab wraps around to the last tab", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<TabNavigation tabs={tabs} activeTab="a" onChange={onChange} panelIdFor={(id) => `panel-${id}`} />);

    screen.getByRole("tab", { name: "Tab A" }).focus();
    await user.keyboard("{ArrowLeft}");

    expect(onChange).toHaveBeenCalledWith("c");
  });
});

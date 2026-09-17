"use client";

import { useRef } from "react";

export interface TabItem {
  id: string;
  label: string;
}

interface TabNavigationProps {
  tabs: TabItem[];
  activeTab: string;
  onChange: (tabId: string) => void;
  /** Associates each tab button with the panel it controls, for screen readers. */
  panelIdFor: (tabId: string) => string;
}

/**
 * Accion Labs Requirement 1.3 (mobile tab navigation) / 1.4 (WCAG 2.1 AA).
 *
 * Implements the standard ARIA "tabs" pattern (role="tablist"/"tab", not a
 * row of plain buttons) per Requirement 1.4's explicit accessibility
 * criteria: aria-selected on the active tab, roving tabindex so Tab only
 * stops once on the tablist (arrow keys move between tabs, matching the
 * pattern users' screen readers expect), visible focus (relies on the
 * existing project-wide focus-visible ring, not a custom one invented
 * here), and real <button> elements throughout.
 */
export function TabNavigation({ tabs, activeTab, onChange, panelIdFor }: TabNavigationProps) {
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  function handleKeyDown(event: React.KeyboardEvent, index: number) {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") {
      nextIndex = (index + 1) % tabs.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (index - 1 + tabs.length) % tabs.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = tabs.length - 1;
    }

    if (nextIndex !== null) {
      event.preventDefault();
      const nextTab = tabs[nextIndex];
      onChange(nextTab.id);
      tabRefs.current[nextTab.id]?.focus();
    }
  }

  return (
    <div role="tablist" aria-label="Workspace panels" className="flex gap-1 border-b">
      {tabs.map((tab, index) => {
        const isActive = tab.id === activeTab;
        return (
          <button
            key={tab.id}
            ref={(el) => {
              tabRefs.current[tab.id] = el;
            }}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={isActive}
            aria-controls={panelIdFor(tab.id)}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => handleKeyDown(event, index)}
            className={
              isActive
                ? "border-b-2 border-primary px-3 py-2 text-sm font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                : "border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            }
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

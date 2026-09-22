"use client";

import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { cn } from "@/lib/utils";

const TooltipProvider = TooltipPrimitive.Provider;
const TooltipTrigger = TooltipPrimitive.Trigger;

/**
 * Self-contained wrapper around Radix's Tooltip.Root — includes its own
 * Provider ancestor rather than requiring every call site (including
 * component tests that render a single citation chip in isolation) to
 * remember to add one. `app/layout.tsx` also wraps the whole app in one
 * shared TooltipProvider for consistent hover-delay behavior across
 * multiple tooltips on the same page; nesting providers like this is
 * expected/harmless in Radix.
 */
function Tooltip(props: React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Root>) {
  return (
    <TooltipPrimitive.Provider>
      <TooltipPrimitive.Root {...props} />
    </TooltipPrimitive.Provider>
  );
}

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        "z-50 max-w-xs overflow-hidden rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-[var(--shadow-md)] duration-[var(--duration-sm)] data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-1 data-[side=top]:slide-in-from-bottom-1",
        className
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
));
TooltipContent.displayName = TooltipPrimitive.Content.displayName;

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };

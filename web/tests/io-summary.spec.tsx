import { test, expect } from "@playwright/test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { IOSummary } from "../src/features/inspector/IOSummary";
import registry from "../src/registry.json" with { type: "json" };
import type { CanvasNode } from "../src/CanvasRegistry";
import { sourceBadge } from "../src/shared/io";

test("source badges describe the displayed data", () => {
  expect(sourceBadge("live", "synthetic", true)).toBe("DEMO");
  expect(sourceBadge("live", "pipeline", true)).toBe("REPLAY");
  expect(sourceBadge("replay", "synthetic")).toBe("REPLAY");
  expect(sourceBadge("live", "pipeline")).toBe("LIVE");
});

test("duplicate summaries do not invent a missing before count", () => {
  const node = registry.nodes.find((node) => node.id === "consolidate") as CanvasNode;
  for (const before of [undefined, 16]) {
    const html = renderToStaticMarkup(createElement(IOSummary, {
      node, rows: [], total: 500, countText: "500 records", before,
    }));
    expect(html).toContain("500 records after");
    expect(html).toContain("Before count not saved");
    expect(html).not.toMatch(/records before|duplicates removed/);
  }
});

for (const [status, label] of [["ok", "Completed"], ["failed", "Failed"]])
  test(`completion summary shows ${label} for ${status}`, () => {
    const node = registry.nodes.find((node) => node.id === "demo") as CanvasNode;
    const html = renderToStaticMarkup(createElement(IOSummary, {
      node, rows: [{status, checks: 1}], total: 1, countText: "1 check",
    }));
    expect(html).toContain(label);
    if (status === "failed") expect(html).not.toContain("Completed");
  });

import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import registry from "../src/registry.json" with { type: "json" };
import { readFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
const names: Record<string, string> = {
  cli: "CLI",
  "run-all": "Run",
  "validate-config": "Validate config",
  "build-constituents": "Build members",
  "estimate-scope": "Plan",
  gate: "Coverage gate",
  publish: "KPI base",
  "model-bakeoff": "Model bakeoff",
  "rebuild-index": "Rebuild index",
  review: "Review queue",
  "extract-step": "Extract",
  "freeze-panel": "Freeze panel",
  "validate-index": "Validate index",
  "supersede-stale": "Supersede stale",
  "prepare-labels": "Label sheet",
  "quality-summary": "Quality summary",
  sec: "SEC client",
  rate: "Rate limit",
  kpi: "KPI registry",
  serve: "Website",
  demo: "DEMO",
  model: "Models",
  raptor: "RAPTOR",
  xbrl: "XBRL",
  "schedule-install": "Install timer",
  "schedule-uninstall": "Remove timer",
};
const label = (key: string) =>
  names[key] ?? key.replaceAll("-", " ").replace(/^./, (c) => c.toUpperCase());
async function open(page: Page) {
  await page.addInitScript((theme) => {
    localStorage.setItem(
      "tresata-canvas-v1",
      JSON.stringify({
        state: { theme, lens: "flow", positions: {}, tourDone: true },
        version: 0,
      }),
    );
  }, test.info().project.use.colorScheme ?? "dark");
  await page.goto("/");
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
}
async function panel(page: Page, id: string) {
  await page.keyboard.press("Control+k");
  await page
    .getByRole("textbox", { name: "Commands" })
    .fill(label(registry.nodes.find((n) => n.id === id)?.label_key ?? id));
  await page.locator(`[data-command="${id}"]`).click();
  await expect(page.locator(".node-panel")).toBeVisible();
  await expect(page.locator(".node-panel .loading")).toHaveCount(0, {
    timeout: 15000,
  });
}
async function wordCount(page: Page, selector: string) {
  return page.locator(selector).evaluate((root) => {
    const count = (value: string) =>
      value
        .trim()
        .split(/\s+/)
        .filter((word) => /[\p{L}\p{N}]/u.test(word)).length;
    const visible = (node: Element) => {
      const style = getComputedStyle(node);
      const box = node.getBoundingClientRect();
      return (
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        box.width > 0 &&
        box.height > 0 &&
        box.bottom > 0 &&
        box.top < innerHeight &&
        box.right > 0 &&
        box.left < innerWidth
      );
    };
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let total = 0;
    while (walker.nextNode()) {
      const parent = walker.currentNode.parentElement;
      if (
        !parent ||
        parent.closest('[data-help-answer],svg,option,[aria-hidden="true"]') ||
        !visible(parent)
      )
        continue;
      total += count(walker.currentNode.textContent ?? "");
    }
    for (const control of root.querySelectorAll<
      HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
    >("input:not([type=checkbox]):not([type=file]),select,textarea")) {
      if (!visible(control)) continue;
      total += count(
        control instanceof HTMLSelectElement
          ? (control.selectedOptions[0]?.textContent ?? "")
          : control.value || control.getAttribute("placeholder") || "",
      );
    }
    return total;
  });
}

test("canvas, theme, text budget and axe", async ({ page }) => {
  await open(page);
  expect(await wordCount(page, ".workstation")).toBeLessThanOrEqual(60);
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
  await mkdir(resolve("../data/screenshots"), { recursive: true });
  await page.screenshot({
    path: resolve(`../data/screenshots/canvas-${test.info().project.name}.png`),
  });
  await page.getByRole("button", { name: "Theme", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute(
    "data-theme",
    test.info().project.use.colorScheme === "dark" ? "light" : "dark",
  );
});

test("live releases remain Production before KPI publication", async ({
  page,
}) => {
  let costRequests = 0;
  await page.route("**/api/v1/index", (route) =>
    route.fulfill({
      json: {
        version: "v1",
        source: "pipeline",
        status: "unavailable",
        snapshots: [],
      },
    }),
  );
  await page.route("**/api/v1/stages", (route) =>
    route.fulfill({
      json: {
        version: "v1",
        source: "pipeline",
        nodes: [{ id: "ingest", status: "done", out_count: 156 }],
      },
    }),
  );
  await page.route("**/api/v1/cost", async (route) => {
    costRequests++;
    await new Promise((resolve) => setTimeout(resolve, 4500));
    await route.fulfill({ json: { metrics: {}, series: [] } });
  });
  await open(page);
  await expect(page.getByText("Production", { exact: true })).toBeVisible({
    timeout: 15000,
  });
  expect(costRequests).toBe(1);
  await expect(
    page.locator('[data-node="ingest"] .flow-label small'),
  ).toHaveText("156");
});

test("every node opens within text budget", async ({ page }) => {
  test.setTimeout(480000);
  await open(page);
  for (const node of registry.nodes) {
    await panel(page, node.id);
    await expect(
      page.getByRole("dialog", { name: label(node.label_key), exact: true }),
    ).toBeVisible();
    expect(await wordCount(page, ".node-panel"), node.id).toBeLessThanOrEqual(
      40,
    );
    await page.keyboard.press("Escape");
  }
});

test("evidence highlights wrong row, verdict writes labels.csv", async ({
  page,
}) => {
  await open(page);
  await page.getByRole("button", { name: "Privacy mode", exact: true }).click();
  await expect(page.getByText("Internal trace", { exact: true })).toBeVisible();
  await panel(page, "extract");
  const output = page.getByRole("region", { name: "OUTPUT", exact: true });
  await output.getByRole("tab", { name: "Evidence", exact: true }).click();
  await expect(output.getByTestId("evidence-row")).toHaveAttribute(
    "data-number-present",
    "false",
  );
  await expect(output.locator("mark")).toBeVisible();
  await output.getByRole("button", { name: "Wrong", exact: true }).click();
  await expect(
    output.getByRole("button", { name: "Wrong", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  const csv = await readFile(
    resolve("../data/ui-verification/canvas/inputs/labels.csv"),
    "utf8",
  );
  expect(csv).toContain("reported_eps");
  expect(csv).toContain("wrong");
  expect(await wordCount(page, ".node-panel")).toBeLessThanOrEqual(40);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({
    path: resolve(
      `../data/screenshots/evidence-${test.info().project.name}.png`,
    ),
  });
  for (const format of ["Table", "JSON", "Schema", "Diff"]) {
    await output.getByRole("tab", { name: format, exact: true }).click();
    expect(await wordCount(page, ".node-panel")).toBeLessThanOrEqual(40);
  }
});

test("help accordion, tour and text budget", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "Help", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "Help", exact: true });
  await drawer.getByRole("button", { name: "What is a node?" }).click();
  await expect(drawer.locator(".help-answer")).toBeVisible();
  expect(await wordCount(page, ".help-drawer")).toBeLessThanOrEqual(40);
  await drawer.getByRole("textbox", { name: "Search" }).fill("verify");
  await drawer
    .getByRole("button", { name: "How do I verify a record?" })
    .click();
  await expect(drawer.locator(".help-answer")).toContainText("J/K");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await drawer.getByRole("button", { name: "Tour", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "Tour", exact: true }),
  ).toBeVisible();
});

test("charts render measured and empty responses", async ({ page }) => {
  const sample = {
    metrics: {
      gate: 10,
      prompt: 1000,
      reasoning: 0,
      content: 500,
      p50: 1.2,
      p95: 2.3,
      cache: 6,
      calls: 10,
      used: 7,
      limit: 1000,
      calls_per_document: 1,
    },
    series: [
      {
        category: "coverage",
        metric: "eps_growth",
        season: "2026Q1",
        value: 0.9,
        denominator: 40,
        status: "ok",
      },
      {
        category: "fields",
        metric: "reported_eps",
        value: 0.9,
        status: "measured",
      },
      {
        category: "reasons",
        metric: "reported_eps:number_not_in_quote",
        value: 2,
        status: "measured",
      },
      {
        category: "cohort",
        metric: "downloaded",
        season: "2026Q1",
        value: 40,
        status: "measured",
      },
      {
        category: "bakeoff",
        metric: "synthetic:free",
        season: "parse_success_rate",
        value: 1,
        status: "measured",
      },
      { category: "plan", metric: "releases", value: 160, status: "estimated" },
    ],
  };
  for (const measured of [true, false]) {
    await page.route(/\/api\/v1\/(coverage|cost|bakeoff|plan)$/, (route) =>
      route.fulfill({ json: measured ? sample : { metrics: {}, series: [] } }),
    );
    await open(page);
    await page.getByRole("button", { name: "Charts", exact: true }).click();
    const lens = page.getByTestId("lens-view");
    for (const key of [
      "funnel",
      "coverage",
      "reasons",
      "fields",
      "cohort",
      "tokens",
      "latency",
      "cache",
      "calls",
      "quota",
      "bakeoff",
      "plan",
    ]) {
      await lens.getByRole("combobox", { name: "Charts" }).selectOption(key);
      await expect(lens.getByTestId("chart-" + key)).toBeVisible();
      expect(await wordCount(page, ".lens-drawer")).toBeLessThanOrEqual(40);
      expect(await lens.textContent()).not.toMatch(/NaN|undefined/);
    }
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
    await page.unroute(/\/api\/v1\/(coverage|cost|bakeoff|plan)$/);
  }
});

test("all charts support unavailable data and schedule", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: "Charts", exact: true }).click();
  const lens = page.getByTestId("lens-view");
  for (const key of [
    "funnel",
    "coverage",
    "reasons",
    "fields",
    "cohort",
    "tokens",
    "latency",
    "cache",
    "calls",
    "quota",
    "bakeoff",
    "plan",
  ]) {
    await lens.getByRole("combobox", { name: "Charts" }).selectOption(key);
    await expect(lens.getByTestId("chart-" + key)).toBeVisible();
    expect(await wordCount(page, ".lens-drawer")).toBeLessThanOrEqual(40);
    expect(await lens.textContent()).not.toMatch(/NaN|undefined/);
    if (key === "coverage")
      await page.screenshot({
        path: resolve(
          `../data/screenshots/quality-${test.info().project.name}.png`,
        ),
      });
  }
  await expect(lens.getByLabel("Schedule", { exact: true })).toBeVisible();
});

test("replay never executes, graph exports exclude identifiers", async ({
  page,
}) => {
  await open(page);
  const mutations: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST") mutations.push(request.url());
  });
  await page.getByRole("button", { name: "Replay", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Run all", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Privacy mode", exact: true }),
  ).toBeDisabled();
  await panel(page, "extract");
  await expect(
    page.getByRole("button", { name: "Execute step", exact: true }),
  ).toBeDisabled();
  expect(await page.locator(".node-panel").textContent()).not.toMatch(
    /UIR\d|UIT\d|0000000001/,
  );
  await page.keyboard.press("Escape");
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export graph", exact: true }).click();
  const download = await downloadPromise;
  const path = await download.path();
  const graph = JSON.parse(await readFile(path!, "utf8"));
  expect(Object.keys(graph).sort()).toEqual(["edges", "nodes", "version"]);
  expect(JSON.stringify(graph)).not.toMatch(
    /UIR\d|UIT\d|document_id|ticker|company|sector|0000000001/,
  );
  expect(mutations).toEqual([]);
  await page.getByLabel("Import graph", { exact: true }).setInputFiles({
    name: "invalid.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ ...graph, document_id: "UIR1" })),
  });
  await expect(page.getByRole("alert")).toContainText("Schema rejected");
});

test("Index and KPI exports are public and replay imports only Index", async ({
  page,
}) => {
  await open(page);
  let index: unknown;
  for (const name of ["Export index", "Export KPIs"]) {
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name, exact: true }).click();
    const download = await pending;
    const value = JSON.parse(await readFile((await download.path())!, "utf8"));
    expect(JSON.stringify(value)).not.toMatch(
      /UIR\d|UIT\d|document_id|ticker|company|sector|evidence_quote|0000000001/,
    );
    if (name === "Export index") index = value;
    else expect(value.records).toBeInstanceOf(Array);
  }
  await page.getByRole("button", { name: "Replay", exact: true }).click();
  await page.getByLabel("Load replay", { exact: true }).setInputFiles({
    name: "index.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify(index)),
  });
  await expect(
    page.getByRole("button", { name: "Run all", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Export KPIs", exact: true }),
  ).toBeDisabled();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("schema rejection and planned stages cannot execute", async ({ page }) => {
  await page.route("**/api/v1/coverage", (route) =>
    route.fulfill({
      json: { version: "v1", metrics: { secret: "not numeric" }, series: [] },
    }),
  );
  await page.addInitScript(() =>
    localStorage.setItem(
      "tresata-canvas-v1",
      JSON.stringify({ state: { tourDone: true, theme: "dark" }, version: 0 }),
    ),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Schema rejected");
  await page.getByRole("alert").click();
  await panel(page, "nowcast");
  await expect(
    page.getByRole("button", { name: "Execute step", exact: true }),
  ).toBeDisabled();
});

test("live demo job survives reload and cancels", async ({ page, request }) => {
  await open(page);
  await panel(page, "demo");
  await page.getByRole("button", { name: "Execute step", exact: true }).click();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Stop", exact: true }),
  ).toBeEnabled();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Stop", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Stop", exact: true }).click();
  await expect
    .poll(
      async () => {
        const response = await request.get("/api/v1/runs");
        return (await response.json())[0]?.status;
      },
      { timeout: 45000 },
    )
    .toBe("cancelled");
});

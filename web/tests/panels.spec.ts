import { test, expect, type Page, type BrowserContext } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { readFileSync } from "node:fs";
import type { CanvasRegistry } from "../src/CanvasRegistry";
const registry: CanvasRegistry = JSON.parse(
  readFileSync(new URL("../src/registry.json", import.meta.url), "utf8"),
);
import { label } from "../src/copy";
import { quantity } from "../src/shared/io";
const demo: StageSnapshot = JSON.parse(
  readFileSync(new URL("../src/demo.json", import.meta.url), "utf8"),
);
import type { StageSnapshot } from "../src/StageSnapshot";
test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

const lastPanel = new WeakMap<Page, string>();
const lastGroup = new WeakMap<Page, string>();
async function open(page: Page, measured = false) {
  await page.addInitScript(
    (theme) =>
      localStorage.setItem(
        "tresata-canvas-v1",
        JSON.stringify({
          state: { theme, tourDone: true, lens: "flow", positions: {} },
          version: 0,
        }),
      ),
    test.info().project.use.colorScheme ?? "dark",
  );
  if (measured)
    await page.route("**/api/v1/index", async (route) => {
      const response = await route.fetch();
      await route.fulfill({
        json: { ...(await response.json()), source: "pipeline" },
      });
    });
  await page.route("**/api/v1/registry", (route) =>
    route.fulfill({ json: registry }),
  );
  if (!measured) {
    await page.route("**/api/v1/stages",route=>route.fulfill({json:{source:"synthetic",nodes:[]}}));
    for (const endpoint of ["coverage", "cost", "bakeoff", "plan"])
      await page.route("**/api/v1/" + endpoint, (route) =>
        route.fulfill({ json: { metrics: {}, series: [] } }),
      );
    await page.route("**/api/v1/runs", (route) => route.fulfill({ json: [] }));
  }
  await page.goto("/");
  await expect(page.locator(".react-flow__node").first()).toBeAttached();
  if(!measured) await page.addStyleTag({content:".workstation {visibility:hidden !important}"});
  if(measured) await expect(page.locator(".react-flow__node").first()).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0, { timeout: 20000 });
}
async function panel(page: Page, id: string) {
  const previous = lastPanel.get(page);
  const index = registry.nodes.findIndex((n) => n.id === id);
  const group =
    registry.nodes[index].group === "sub"
      ? "main"
      : registry.nodes[index].group;
  if ((lastGroup.get(page) ?? "main") !== group) {
    if (await page.locator(".node-panel").isVisible()) {
      await page.keyboard.press("Escape");
      await expect(page.locator(".node-panel")).toHaveCount(0);
    }
    const names: Record<string, string> = {
      main: "Production",
      ingest: "Ingest",
      extract: "Extract",
      maintenance: "Maintenance",
      demo: "DEMO",
    };
    if(await page.locator(".workstation").isVisible()) await page
      .locator(".canvas-switch")
      .getByRole("button", { name: names[group] ?? group, exact: true })
      .click();
  }
  lastGroup.set(page, group);

  if (
    previous &&
    registry.nodes[index - 1]?.id === previous &&
    (await page.locator(".node-panel").isVisible())
  ) {
    await page.keyboard.press("Alt+ArrowRight");
  } else {
    await page.keyboard.press("Control+k");
    await page
      .getByRole("textbox", { name: "Commands" })
      .fill(label(registry.nodes[index].label_key));
    await page.locator(`[data-command="${id}"]`).click();
  }
  lastPanel.set(page, id);
  await expect(page.locator(".node-panel")).toBeVisible();
  await expect(page.locator(".node-panel")).toHaveAttribute("data-node",id);
  await expect(page.getByRole("region",{name:"INPUT",exact:true})).toHaveCount(1);
  await expect(page.getByRole("region",{name:"OUTPUT",exact:true})).toHaveCount(1);
  await expect(page.locator(".io-shimmer")).toHaveCount(0, { timeout: 20000 });
}

test.describe("newcomer panels", () => {
  let galleryPage: Page;
  let galleryContext: BrowserContext;
  test.beforeAll(async ({ browser }, info) => {
    if (info.project.name !== "1440-dark") return;
    galleryContext = await browser.newContext();
    galleryPage = await galleryContext.newPage();
    await open(galleryPage);
  });
  test.afterAll(async () => {
    await galleryContext?.close();
  });
for (const node of registry.nodes) test(`newcomer pane: ${node.id}`, async () => {
  const page = galleryPage;
  test.skip(
    test.info().project.name !== "1440-dark",
    "This test captures all four viewport/theme combinations itself",
  );
  test.setTimeout(180000);
  const root = resolve("../data/screenshots/panels");
  await mkdir(root, { recursive: true });

    await panel(page, node.id);
    const input = page.getByRole("region", { name: "INPUT", exact: true });
    const output = page.getByRole("region", { name: "OUTPUT", exact: true });
    await expect(input.locator(".io-source")).not.toBeEmpty();
    await expect(input.getByTestId("io-count")).toHaveText(
      /\d[\d,]* (members?|company-quarters?|releases?|files?|texts?|records?|checks?|flags?|index rows?|KPIs?)/,
    );
    await expect(input.locator(".io-plain")).toHaveText(
      node.io.takes.plain_line,
    );
    if (node.capability !== "planned")
      await expect(input.getByTestId("summary-tile")).toBeVisible();
    else await expect(input).toContainText("Not built yet");
    const count = quantity(
      node,
      demo.nodes.find(
        (n) => n.id === node.id,
      ) as StageSnapshot["nodes"][number],
    );
    if (count) {
      await expect(output.getByTestId("io-count")).toHaveText(count.text);
      await expect(output.locator(".summary-total")).toHaveText(count.text);
    }
    for (const pane of [input, output]) {
      await expect(pane.locator("table")).toHaveCount(0);
      await expect(pane.locator(".pane-selects")).toHaveCount(0);
      for (const card of await pane.getByTestId("example-card").all())
        expect(await card.locator("dt").count()).toBeGreaterThanOrEqual(3);
      const text = await pane.innerText();
      expect(text).not.toMatch(
        /0000123456|UIR\d|UIT\d|document_id|member_token|effective_from|reported_eps|evidence_quote/,
      );
      await expect(pane.locator(".io-footer b")).toHaveText("DEMO");
    }
    const sentence = `${label(node.label_key)} takes ${await input.getByTestId("io-count").innerText()} from ${await input.locator(".io-source").innerText()}: ${await input.locator(".io-plain").innerText()}.`;
    console.log(sentence);

    for (const width of [1440, 1280])
      for (const theme of ["dark", "light"]) {
        await page.setViewportSize({ width, height: 900 });
        await page.evaluate(async (theme) => {
          document.documentElement.dataset.theme = theme;
          document.body.getBoundingClientRect();
          await Promise.all(
            document
              .getAnimations()
              .map((animation) => animation.finished.catch(() => {})),
          );
        }, theme);
        if (width === 1280)
          expect(
            (await new AxeBuilder({ page }).include(".node-panel").analyze())
              .violations,
            node.id + " " + theme,
          ).toEqual([]);
        await page.locator(".node-panel").screenshot({
          path: resolve(root, `${node.id}-${width}-${theme}.png`),
          animations: "disabled",
        });
      }
  await writeFile(
    resolve(root, `newcomer-${node.id}.txt`),
    sentence,
  );
});

});

test("measured fixture counts use the same quantity as canvas and edge labels", async ({
  page,
  request,
}) => {
  test.skip(
    test.info().project.name !== "1440-dark",
    "Counts share the same code at both widths and themes",
  );
  test.setTimeout(360000);
  const stages: StageSnapshot = await (
    await request.get("/api/v1/stages")
  ).json();
  await open(page, true);
  await page.setViewportSize({width:1440,height:1600});
  await expect(page.locator(".pipeline-badge")).toContainText("LIVE");
  for (const node of registry.nodes) {
    const count = quantity(
      node,
      stages.nodes.find((n) => n.id === node.id),
    );
    await panel(page, node.id);
    const output = page.getByRole("region", { name: "OUTPUT", exact: true });
    if (count) {
      await expect(output.getByTestId("io-count")).toHaveText(count.text);
      await expect(output.locator(".summary-total")).toHaveText(count.text);
    }
    await expect(output.locator(".io-footer b")).toHaveText("LIVE");
    console.log(
      label(node.label_key) + ": " + (count?.text ?? "No output quantity"),
    );
    if (["build-constituents", "estimate-scope", "extract"].includes(node.id))
      await page
        .locator(".node-panel")
        .screenshot({
          path: resolve(
            "../data/screenshots/panels",
            `live-${node.id}-1440-dark.png`,
          ),
        });
    for (const view of [
      "build-constituents",
      "estimate-scope",
      "extract",
    ].includes(node.id)
      ? ["Example", "Table", "JSON", "Fields"]
      : []) {
      await output.getByRole("button", { name: view, exact: true }).click();
      expect(await output.innerText()).not.toMatch(
        /UIR\d|UIT\d|document_id|0000000001|evidence_quote/,
      );
    }
    const canvas = page.locator(`[data-node="${node.id}"] .flow-label small`);
    if (count) await expect(canvas).toHaveText(count.text);
    for (const edge of registry.edges.filter(
      (e) => e.source === node.id && !e.sub,
    )) {
      const edgeLabel = page.locator(
        `.react-flow__edge[aria-label="Edge from ${node.id} to ${edge.target}"] .edge-number`,
      );
      if (count && (await edgeLabel.count()))
        await expect(edgeLabel).toHaveText(count.text);
    }
  }
});

test("pseudonyms stay stable in a page and change in a new session", async ({
  browser,
}) => {
  test.skip(
    test.info().project.name !== "1440-dark",
    "Session privacy is independent of viewport and theme",
  );
  const names: string[] = [];
  for (let i = 0; i < 2; i++) {
    const context = await browser.newContext();
    const page = await context.newPage();
    await open(page);
    await panel(page, "build-constituents");
    const card = page
      .getByRole("region", { name: "OUTPUT", exact: true })
      .getByTestId("example-card");
    const name = await card.locator("dd").first().innerText();
    expect(name).toMatch(/^Member \d+$/);
    await page.keyboard.press("Escape");
    await expect(page.locator(".node-panel")).toHaveCount(0);
    await panel(page, "build-constituents");
    await expect(card.locator("dd").first()).toHaveText(name);
    names.push(name);
    await context.close();
  }
  expect(names[0]).not.toEqual(names[1]);
});

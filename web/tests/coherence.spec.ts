import { test, expect, type Page } from "@playwright/test";

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
});

const upstream = {
  node: "build-constituents",
  side: "input",
  view: "index",
  status: "available",
  total: 1,
  offset: 0,
  columns: ["setting", "setting_value", "kind"],
  rows: [{ setting: "Sample size", setting_value: 3, kind: "Number" }],
  config_hash: "test-config",
  runs: ["validated-settings-run"],
  upstream: ["validate-config"],
};
const job = {
  version: "v1",
  id: "individual-build-run",
  workflow_id: "command",
  status: "queued",
  stage: "build-constituents",
  completed: 0,
  total: 1,
  cancel_requested: false,
  created_at: "2026-11-03T00:00:00Z",
};

async function open(page: Page, holdInput = false, badge = "DEMO") {
  let submitted: Record<string, unknown> | undefined;
  let release: () => void = () => {};
  let requested = false;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.addInitScript(() =>
    localStorage.setItem(
      "tresata-canvas-v1",
      JSON.stringify({
        state: { theme: "dark", tourDone: true, lens: "flow", positions: {} },
        version: 0,
      }),
    ),
  );
  await page.route("**/api/v1/index", (route) =>
    route.fulfill({
      json: {
        version: "v1",
        source: "pipeline",
        status: badge === "REPLAY" ? "available" : "unavailable",
        snapshots: [],
      },
    }),
  );
  await page.route("**/api/v1/stages", (route) =>
    route.fulfill({
      json: {
        source: "pipeline",
        nodes: submitted
          ? [{ id: "validate-config", status: "done", out_count: 1 }]
          : [],
      },
    }),
  );
  await page.route("**/api/v1/runs", (route) => {
    if (route.request().method() === "POST") {
      submitted = route.request().postDataJSON();
      return route.fulfill({ status: 202, json: job });
    }
    return route.fulfill({ json: submitted ? [job] : [] });
  });
  await page.route("**/api/v1/runs/*/events", (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(
    "**/api/v1/nodes/build-constituents/input*",
    async (route) => {
      requested = true;
      if (holdInput) await pending;
      await route.fulfill({ json: upstream });
    },
  );
  for (const endpoint of ["coverage", "cost", "bakeoff", "plan"])
    await page.route("**/api/v1/" + endpoint, (route) =>
      route.fulfill({ json: { metrics: {}, series: [] } }),
    );
  await page.goto("/");
  await expect(page.locator(".pipeline-badge")).toContainText(badge);
  await expect(page.getByRole("alert")).toHaveCount(0);
  await page.keyboard.press("Control+k");
  await page.getByRole("textbox", { name: "Commands" }).fill("Build members");
  await page.locator('[data-command="build-constituents"]').click();
  await expect(page.locator(".node-panel")).toBeVisible();
  return { submission: () => submitted, requested: () => requested, release };
}

for (const surface of ["panel", "toolbar"])
  test(`${surface} resolves real upstream runs from a DEMO preview`, async ({
    page,
  }) => {
    const state = await open(page);
    if (surface === "toolbar") {
      await page.keyboard.press("Escape");
      await expect(page.locator(".node-panel")).toHaveCount(0);
      await page
        .getByRole("button", { name: "Run selected", exact: true })
        .click();
    } else
      await page
        .getByRole("button", { name: "Execute step", exact: true })
        .click();
    await expect.poll(() => state.submission()).toBeTruthy();
    expect(state.submission()).toMatchObject({
      command_id: "build-constituents",
      node_id: "build-constituents",
      upstream_run_id: "validated-settings-run",
    });
    await expect(page.locator(".pipeline-badge")).toContainText("LIVE");
    expect(state.requested()).toBe(true);
  });

test("switching to Replay during prerequisite lookup never submits a run", async ({
  page,
}) => {
  const state = await open(page, true);
  await page.getByRole("button", { name: "Execute step", exact: true }).click();
  await expect.poll(() => state.requested()).toBe(true);
  await page
    .locator(".parameters-body")
    .getByRole("button", { name: "Replay", exact: true })
    .click();
  const response = page.waitForResponse((response) =>
    response.url().includes("/nodes/build-constituents/input"),
  );
  state.release();
  await response;
  await expect(
    page.getByRole("button", { name: "Execute step", exact: true }),
  ).toBeDisabled();
  expect(state.submission()).toBeUndefined();
});

test("saved snapshots explain read-only mode and disable execution", async ({ page }) => {
  await page.route("**/api/v1/session", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ json: { ...(await response.json()), read_only: true } });
  });
  await open(page, false, "REPLAY");
  await expect(page.getByRole("status")).toContainText("Saved snapshot");
  await expect(page.locator(".io-footer b")).toHaveText(["REPLAY", "REPLAY"]);
  await expect(page.getByRole("button", { name: "Execute step", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Run selected", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Run all", exact: true })).toBeDisabled();
});

for (const [detail, message] of [
  [
    "inspector requires a validated upstream run",
    "Run the previous step first",
  ],
  ["upstream artifacts changed", "Inputs changed. Rerun the previous step."],
])
  test(
    "execution gives a useful prerequisite message: " + detail,
    async ({ page }) => {
      await open(page);
      await page.route("**/api/v1/runs", (route) =>
        route.request().method() === "POST"
          ? route.fulfill({ status: 409, json: { detail } })
          : route.fulfill({ json: [] }),
      );
      await page
        .getByRole("button", { name: "Execute step", exact: true })
        .click();
      await expect(page.getByRole("alert")).toHaveText(message);
    },
  );

test("real Pause and Resume buttons complete and expose action receipts", async ({
  page,
  request,
}) => {
  test.setTimeout(120000);
  await page.addInitScript(() =>
    localStorage.setItem(
      "tresata-canvas-v1",
      JSON.stringify({
        state: { theme: "dark", tourDone: true, lens: "flow", positions: {} },
        version: 0,
      }),
    ),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
  for (const [id, search, paused] of [
    ["schedule-pause", "pause", true],
    ["schedule-resume", "resume", false],
  ] as const) {
    await page.keyboard.press("Control+k");
    await page.getByRole("textbox", { name: "Commands" }).fill(search);
    await page.locator(`[data-command="${id}"]`).click();
    await expect(page.locator(".node-panel")).toHaveAttribute("data-node", id);
    const submitted = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().endsWith("/api/v1/runs"),
    );
    await page
      .getByRole("button", { name: "Execute step", exact: true })
      .click();
    const created = await (await submitted).json();
    await expect
      .poll(
        async () => {
          const run = await (
            await request.get("/api/v1/runs/" + created.id)
          ).json();
          return run.status;
        },
        { timeout: 45000 },
      )
      .toBe("succeeded");
    const schedule = await (await request.get("/api/v1/schedule")).json();
    expect(schedule.paused).toBe(paused);
    const output = page.getByRole("region", { name: "OUTPUT", exact: true });
    await expect(output.getByTestId("io-count")).toHaveText("1 check", {
      timeout: 15000,
    });
    await expect(output.getByTestId("example-card")).toContainText("succeeded", { timeout: 15000 });
    await page.keyboard.press("Escape");
    await expect(page.locator(".node-panel")).toHaveCount(0);
  }
});

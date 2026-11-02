import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  timeout: 60000,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:18765",
    trace: "retain-on-failure",
    launchOptions: process.env.CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
      : {},
  },
  webServer: {
    command:
      "../.venv/bin/python ../scripts/prepare_ui_fixtures.py && ../.venv/bin/python -m nowcast.app serve --config ../data/ui-verification/canvas/config.yaml --port 18765",
    url: "http://127.0.0.1:18765/api/v1/session",
    reuseExistingServer: false,
    env: {
      DATA_DIR: new URL("../data/ui-verification/canvas", import.meta.url)
        .pathname,
      NOWCAST_INTERNAL_TRACE: "1",
      TRESATA_IGNORE_LOCAL_CONFIG: "1",
      PYTHONPATH: new URL("../tests/offline", import.meta.url).pathname,
    },
  },
  projects: [1280, 1440].flatMap((width) =>
    (["dark", "light"] as const).map((theme) => ({
      name: `${width}-${theme}`,
      use: { viewport: { width, height: 900 }, colorScheme: theme },
    })),
  ),
});

import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";

const root = path.resolve("../..");
const shots = path.join(root, "docs/screenshots/after");
const fixtures = path.join(root, "tests/fixtures");
const names = {
  door: "Door",
  acv: "ACV (air conditioning)",
  rail: "Rail corrugation",
  shm: "Structural health (SHM)",
};
type Sub = keyof typeof names;
const subs = Object.keys(names) as Sub[];
const originals = {
  door: "Door/Test.csv",
  acv: "ACV/Test/acv_test_case.xlsx",
  rail: "Rail_Corrugation/Test/Test1.csv",
  shm: "SHM/Test/test01.csv",
};
// The exported predictions for these official files (prediction_exports/predictions.zip).
const exported = {
  door: { csv: "door_predictions.csv", header: "start_time,end_time,prediction", rows: 38, text: "8 of 38" },
  acv: { csv: "acv_predictions.csv", header: "file_id,ranked_cars", rows: 1, text: "Car 03" },
  rail: { csv: "rail_predictions.csv", header: "file_id,prediction", rows: 1, text: "Normal" },
  shm: { csv: "shm_predictions.csv", header: "file_id,prediction", rows: 1, text: "0.03218" },
};
async function downloadPrediction(page: Page) {
  const dl = page.waitForEvent("download");
  await page
    .locator("#prediction")
    .getByRole("link", { name: /Download prediction CSV/ })
    .click();
  const file = await dl;
  const lines = (await fs.readFile((await file.path())!, "utf8"))
    .trim()
    .split("\n");
  return { name: file.suggestedFilename(), lines };
}

async function capture(page: Page, name: string) {
  await fs.mkdir(shots, { recursive: true });
  await page.screenshot({
    path: path.join(shots, name + ".png"),
    fullPage: true,
  });
}
async function accessible(page: Page) {
  const a = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(
    a.violations,
    JSON.stringify(
      a.violations.map((v) => ({
        id: v.id,
        nodes: v.nodes.map((n) => n.target),
      })),
    ),
  ).toEqual([]);
}
async function upload(page: Page, file: string) {
  await page.goto("/analyze");
  await page.getByLabel("Recording file", { exact: true }).setInputFiles(file);
  await expect(
    page.getByRole("heading", { name: "File validation" }),
  ).toBeVisible();
  const confirm = page.getByRole("button", { name: "Confirm SHM stress" });
  if (await confirm.isVisible()) await confirm.click();
}
async function analyse(page: Page, sub: Sub) {
  await page
    .getByRole("button", { name: "Analyse recording", exact: true })
    .click();
  await expect(page).toHaveURL(/\/runs\//);
  await expect(
    page.getByRole("heading", { name: names[sub], exact: true }),
  ).toBeVisible();
  await expect(page.locator(".primary-action")).toBeVisible();
  await expect(page.locator(".chart-panel svg").first()).toBeVisible();
}

for (const sub of subs) {
  for (const kind of [
    "healthy",
    "faulty",
    "borderline",
    "wrong_scale",
  ] as const) {
    test(`${sub}: ${kind} real upload`, async ({ page }) => {
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(e.message));
      await upload(page, path.join(fixtures, sub, kind + ".csv"));
      if (kind === "wrong_scale") {
        await expect(page.getByTestId("condition")).toHaveText("Blocked");
        await expect(page.getByRole("main").getByRole("alert")).toContainText(
          /scale|units|calibration/i,
        );
        await expect(
          page.getByRole("button", { name: "Analyse recording" }),
        ).toHaveCount(0);
        await capture(page, `${sub}-error`);
        await accessible(page);
      } else {
        await expect(page.getByLabel("Detected subsystem")).toHaveValue(sub);
        await expect(page.locator("#validation")).toContainText("rows");
        await analyse(page, sub);
        if (kind === "faulty")
          await expect(page.getByTestId("condition")).toHaveText(
            "Action required",
          );
        if (kind === "healthy")
          await expect(page.getByTestId("condition")).not.toHaveText(
            "Action required",
          );
        if (kind === "borderline")
          await expect(page.getByTestId("condition")).toHaveText("Watch");
        await expect(page.locator(".alternative-list > li")).toHaveCount(3);
        expect(
          await page.locator(".chart-panel").count(),
        ).toBeGreaterThanOrEqual(2);
        for (const link of await page
          .locator(".primary-action .evidence-list a")
          .all()) {
          const target = await link.getAttribute("href");
          expect(target).toMatch(/^#/);
          await expect(page.locator(target!)).toBeVisible();
        }
        await expect(page.locator(".data-details")).not.toHaveAttribute("open");
        await page
          .getByRole("button", { name: "Zoom in", exact: true })
          .first()
          .click();
        await expect(
          page.getByRole("button", { name: "Reset", exact: true }).first(),
        ).toBeEnabled();
        await page
          .getByRole("button", { name: "Reset", exact: true })
          .first()
          .click();
        const svg = page.locator(".chart-panel svg").first();
        await svg.hover();
        const trace = page
          .locator(".chart-panel figure")
          .filter({ has: page.getByRole("toolbar") })
          .first();
        await trace.locator("svg").hover();
        await expect(trace.locator('[aria-live="polite"]')).toContainText("→");
        if (kind === "faulty") {
          await capture(page, `${sub}-faulty-results`);
          await accessible(page);
          await page.locator(".data-details > summary").click();
          await expect(
            page.locator(".data-details tbody tr").last(),
          ).toBeVisible();
          await capture(page, `${sub}-faulty-details`);
          const dl = page.waitForEvent("download");
          await page
            .getByRole("link", { name: "Download findings CSV" })
            .click();
          const downloaded = await dl;
          const csv = await fs.readFile((await downloaded.path())!, "utf8");
          expect(csv).toContain("confidence_basis");
          expect(csv).toContain("Action required");
        }
      }
      expect(errors).toEqual([]);
    });
  }
  test(`${sub}: original recording and responsive screenshots`, async ({
    page,
  }) => {
    await page.goto("/analyze");
    await capture(page, `${sub}-upload`);
    await upload(
      page,
      path.join(
        root,
        "NebulaX-Hackathon-ProblemStatement/PS3/02_Datasets",
        originals[sub],
      ),
    );
    await capture(page, `${sub}-validation`);
    await accessible(page);
    await analyse(page, sub);
    const prediction = page.locator("#prediction");
    await expect(prediction).toContainText(exported[sub].text);
    if (sub === "door")
      await expect(prediction.locator("tbody tr")).toHaveCount(38);
    if (sub === "acv")
      await expect(prediction.locator(".ranking > li")).toHaveText(
        ["03", "04", "01", "08", "07", "06", "02", "05"].map(
          (car) => new RegExp(`Car ${car}`),
        ),
      );
    const csv = await downloadPrediction(page);
    expect(csv.name).toBe(exported[sub].csv);
    expect(csv.lines[0]).toBe(exported[sub].header);
    expect(csv.lines).toHaveLength(exported[sub].rows + 1);
    for (const width of [1440, 1280, 768]) {
      await page.setViewportSize({ width, height: 1000 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
      ).toBe(true);
      await capture(page, `${sub}-results-${width}`);
      await accessible(page);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator(".data-details > summary").click();
    await capture(page, `${sub}-details`);
    await page.locator(".alternative-list summary").first().click();
    await capture(page, `${sub}-alternative-detail`);
  });
}

test("sample downloads, keyboard and empty state", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/analyze$/);
  await expect(
    page.getByRole("heading", { name: "Analyse a recording" }),
  ).toBeVisible();
  await expect(page.locator(".drop-zone")).toHaveCount(1);
  for (const sub of subs) {
    const r = await page.request.get(`/api/v1/samples/${sub}`);
    expect(r.ok()).toBe(true);
    expect(r.headers()["x-sentinel-source"]).toBe("official-test-input");
    const actual = createHash("sha256").update(await r.body()).digest("hex");
    const official = await fs.readFile(path.join(root, "NebulaX-Hackathon-ProblemStatement/PS3/02_Datasets", originals[sub]));
    expect(actual).toBe(createHash("sha256").update(official).digest("hex"));
  }
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("link", { name: "Skip to content" }),
  ).toBeFocused();
  await accessible(page);
});

test("sample links appear only when the server has the official test files", async ({
  page,
}) => {
  await page.goto("/analyze");
  const samples = page.getByRole("link", { name: /official test file/ });
  await expect(samples).toHaveCount(4);
  await page.route("**/api/v1/datasets", (route) =>
    route.fulfill({ json: { datasets: [], root: "/data" } }),
  );
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Analyse a recording" }),
  ).toBeVisible();
  await expect(page.locator(".sample-list")).toContainText("Rail corrugation");
  await expect(samples).toHaveCount(0);
  await accessible(page);
});

test("wrong subsystem is rejected inline and can be corrected", async ({
  page,
}) => {
  await upload(page, path.join(fixtures, "door", "healthy.csv"));
  await page.getByLabel("Detected subsystem").selectOption("rail");
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Cannot interpret",
  );
  await expect(page.getByLabel("Detected subsystem")).toHaveValue("door");
  await page.getByLabel("Detected subsystem").selectOption("door");
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  await analyse(page, "door");
});

test("repeat upload is deterministic; switching does not reload", async ({
  page,
}) => {
  await upload(page, path.join(fixtures, "door", "faulty.csv"));
  await analyse(page, "door");
  const first = await page.locator(".primary-action").innerText();
  await page.evaluate(() => {
    (window as Window & { testMarker?: string }).testMarker = "same-document";
  });
  await page
    .getByRole("link", { name: "Upload another file / switch subsystem" })
    .click();
  expect(
    await page.evaluate(
      () => (window as Window & { testMarker?: string }).testMarker,
    ),
  ).toBe("same-document");
  await page
    .getByLabel("Recording file", { exact: true })
    .setInputFiles(path.join(fixtures, "door", "faulty.csv"));
  await analyse(page, "door");
  expect(await page.locator(".primary-action").innerText()).toBe(first);
  await page
    .getByRole("link", { name: "Upload another file / switch subsystem" })
    .click();
  await page
    .getByLabel("Recording file", { exact: true })
    .setInputFiles(path.join(fixtures, "acv", "healthy.csv"));
  await expect(page.getByLabel("Detected subsystem")).toHaveValue("acv");
  await analyse(page, "acv");
});

test("empty upload and unreachable API explain recovery", async ({ page }) => {
  await upload(page, path.join(fixtures, "door", "empty.csv"));
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "empty",
  );
  await page.route("**/api/v1/runs", (route) =>
    route.abort("connectionrefused"),
  );
  await page
    .getByLabel("Recording file", { exact: true })
    .setInputFiles(path.join(fixtures, "door", "healthy.csv"));
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Cannot reach",
  );
  await capture(page, "service-unavailable");
});

test("100k-row Rail file crosses the real web proxy intact", async ({
  page,
}) => {
  await upload(page, path.join(fixtures, "rail", "large.csv"));
  await expect(page.locator("#validation")).toContainText("100,000");
  await analyse(page, "rail");
  await page.locator(".data-details > summary").click();
  await expect(page.locator(".data-details")).toContainText("100,000");
});

test("official Rail batch lists every prediction and downloads its CSV", async ({
  page,
}) => {
  await page.goto("/history");
  await page
    .getByText("Analyse an official test batch", { exact: false })
    .click();
  await page.getByRole("button", { name: /Rail.*68 files/ }).click();
  await expect(page.getByText("68 of 68 files ready.")).toBeVisible();
  await page.getByRole("button", { name: "Analyse batch" }).click();
  const prediction = page.locator("#prediction");
  await expect(prediction).toContainText("54 Normal", { timeout: 90_000 });
  await expect(prediction).toContainText("7 Side I ");
  await expect(prediction).toContainText("7 Side II");
  await expect(prediction.locator("tbody tr")).toHaveCount(68);
  await prediction.getByRole("button", { name: "Test9.csv" }).click();
  await expect(page.locator(".result-heading .file-name")).toHaveText(
    "Test9.csv",
  );
  await capture(page, "rail-batch-prediction");
  await accessible(page);
  const csv = await downloadPrediction(page);
  expect(csv.name).toBe("rail_predictions.csv");
  expect(csv.lines[0]).toBe("file_id,prediction");
  expect(csv.lines).toHaveLength(69);
  expect(csv.lines).toContain("Test9.csv,Side II");
});

test("history, bundle preparation and methods stay available", async ({
  page,
}) => {
  await page.goto("/history");
  await expect(
    page.getByRole("heading", { name: "Past analyses" }),
  ).toBeVisible();
  await capture(page, "history");
  await page.getByText("Export prediction bundle", { exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Build predictions.zip" }),
  ).toBeVisible();
  await capture(page, "bundle");
  const inventory = await page.request.get("/api/v1/prediction_exports/inventory");
  const { candidates } = await inventory.json();
  for (const sub of subs) {
    expect(candidates[sub].every((c: { matches_official_test: boolean }) => c.matches_official_test)).toBe(true);
    const choices = page.getByLabel(`${names[sub]} analysis`).locator("option");
    await expect(choices).toHaveCount(candidates[sub].length + 1);
  }
  await expect(page.getByText(/synthetic, training and modified files are excluded/i)).toBeVisible();
  await page
    .getByText("Analyse an official test batch", { exact: false })
    .click();
  await expect(page.getByRole("button", { name: /Door.*files/ })).toBeVisible();
  await page.getByRole("button", { name: /Door.*files/ }).click();
  await expect(page.getByText("1 of 1 files ready.")).toBeVisible();
  await page.getByRole("button", { name: "Analyse batch" }).click();
  await expect(
    page.getByRole("heading", { name: "Door", exact: true }),
  ).toBeVisible();
  for (const route of ["method", "learn", "attention"]) {
    await page.goto(`/${route}`);
    await expect(page.locator("h1")).toBeVisible();
    await capture(page, route);
  }
});

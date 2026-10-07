import { test, expect } from "@playwright/test";
test("real bidirectional exchange and lifecycle", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByText("IDLE · Connected", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Modem profile")).toContainText(
    "Bell 103 · 300 bit/s · functional FSK",
  );
  await expect(
    page.getByText(/hardware interoperability unverified/),
  ).toBeVisible();
  await page.getByLabel("Text from caller").fill("Hello B");
  await page.getByLabel("Text from answerer").fill("Hello A");
  await page
    .getByRole("button", { name: "Queue", exact: true })
    .first()
    .click();
  await page.getByRole("button", { name: "Queue", exact: true }).last().click();
  await page.getByRole("button", { name: "Start call", exact: false }).click();
  await expect(page.getByLabel("Caller received text")).toHaveText("Hello A", {
    timeout: 12000,
  });
  await expect(page.getByLabel("Answerer received text")).toHaveText(
    "Hello B",
    { timeout: 12000 },
  );
  await page.getByLabel("Bandpass", { exact: true }).selectOption("flat");
  await expect(page.getByText(/Applied at/)).toBeVisible();
  await page.getByRole("button", { name: "Hang up", exact: true }).click();
  await expect(
    page.getByText("IDLE · Connected", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Restart", exact: false }).click();
  await expect(page.getByLabel("Caller received text")).toHaveText(
    "Waiting for decoded text…",
  );
  await expect(
    page.getByText("LIVE · Connected", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Text from caller").fill("é");
  await page.getByRole("button", { name: "Send", exact: true }).first().click();
  await expect(page.getByRole("alert")).toContainText("Use 7-bit ASCII");
});
test("mobile controls stay within the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Modem Lab", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(375);
  await page.getByLabel("Use light appearance").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("native audio startup, monitor changes and hangup", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByText("IDLE · Connected", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Start call", exact: false }).click();
  await page.getByLabel("Listen to signal").selectOption("3");
  await page.getByRole("button", { name: "Enable / resume audio" }).click();
  await expect(page.locator("footer")).toContainText("Audio: playing", {
    timeout: 12000,
  });
  await page.getByLabel("Listen to signal").selectOption("4");
  await expect(page.locator("footer")).toContainText("Audio: playing", {
    timeout: 12000,
  });
  await page.getByLabel("Listen to signal").selectOption("0");
  await expect(page.locator("footer")).toContainText("Audio: muted");
  await page.getByRole("button", { name: "Hang up", exact: true }).click();
  await expect(page.locator("footer")).toContainText("Audio: stopped");
});

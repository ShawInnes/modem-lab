import { test, expect } from "@playwright/test";

test("receiver views explain actual tone decisions and differential phase timing", async ({ page }) => {
  const endpoint = { state: "connected", carrier_lock: true, confidence: 0.9, framing_errors: 0, queued: 0 };
  const common = { sample_index: 48000, timing_locked: true, timing_note: "Fixed nominal clock after audio-derived acquisition." };
  await page.routeWebSocket(/\/ws\/control$/, (route) => {
    route.send(JSON.stringify({ type: "hello", version: 1, session_id: "diagnostic-test", generation: 1 }));
    route.send(JSON.stringify({
      type: "state", generation: 1, sample_index: 48000, active: true,
      config: { profile: "bell103", snr_db: 40, delay_ms: 20, echo_attenuation_db: 30, bandpass: "telephone", seed: 103 },
      endpoints: { caller: endpoint, answerer: endpoint },
      metrics: { processing_ms: 2, overruns: 0, display_gaps: 0 },
      diagnostics: {
        caller: { ...common, mode: "fsk", symbol_samples: 160, trace: [[47840, -0.8], [47920, 0.2], [48000, 0.9]], symbols: [[48000, 0.003, 0.05, 1, 0.9]] },
        answerer: { ...common, mode: "dqpsk", symbol_samples: 80, trace: [[47920, 0.2], [47960, 0.7], [48000, 0.95]], symbols: [[48000, 0.02, 0.99, 0, 0.94]] },
      },
    }));
  });
  await page.routeWebSocket(/\/ws\/data\//, () => {});
  await page.goto("/");
  const receivers = page.getByRole("region", { name: "Receiver diagnostics", exact: true });
  await expect(receivers.getByRole("img")).toHaveCount(2);
  await expect(receivers).toContainText("Above the diagonal favors bit 1");
  await expect(receivers).toContainText("phase change between two received symbols");
  await expect(receivers).toContainText("300 symbols/s");
  await expect(receivers).toContainText("600 symbols/s");
  await page.getByLabel("Receiver diagnostic view").selectOption("eye");
  await expect(receivers).toContainText("wide opening at the center");
  await expect(receivers).toContainText("timing envelope, not a binary eye");
  await expect(page.getByRole("img", { name: "Caller receiver timing view" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Answerer receiver timing view" })).toBeVisible();
  await page.setViewportSize({ width: 375, height: 900 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

import { test, expect } from "@playwright/test";

// Exercise presentation gestures with protocol packets, independently of the
// single controlling browser. Real modulation/transport are covered separately.
test("both plots share zoom, wheel, drag, history and live navigation", async ({
  page,
}) => {
  const endpoint = {
    state: "connected",
    carrier_lock: true,
    confidence: 0.7,
    framing_errors: 0,
    queued: 0,
  };
  await page.routeWebSocket(/\/ws\/control$/, (route) => {
    route.send(
      JSON.stringify({
        type: "hello",
        version: 1,
        session_id: "plot-test",
        generation: 1,
      }),
    );
    route.send(
      JSON.stringify({
        type: "state",
        generation: 1,
        sample_index: 30 * 48000,
        active: true,
        config: {
          snr_db: 40,
          delay_ms: 20,
          echo_attenuation_db: 30,
          bandpass: "telephone",
          seed: 103,
        },
        endpoints: { caller: endpoint, answerer: endpoint },
        metrics: { processing_ms: 2, overruns: 0, display_gaps: 0 },
      }),
    );
  });
  await page.routeWebSocket(/\/ws\/data\//, (route) => {
    const frames = 960,
      columns = 100,
      bins = 171;
    const buffer = new ArrayBuffer(
      40 + 16 * frames + 8 * columns + 4 * columns * bins,
    );
    const view = new DataView(buffer);
    view.setUint32(0, 0x42414c4d, true);
    view.setUint16(4, 1, true);
    view.setUint16(6, 1, true);
    view.setUint32(8, 1, true);
    view.setUint32(12, 0, true);
    view.setBigUint64(16, BigInt(30 * 48000 - frames), true);
    view.setUint32(24, 48000, true);
    view.setUint32(28, frames, true);
    view.setUint32(32, columns, true);
    view.setUint32(36, bins, true);
    for (let i = 0; i < columns; i++)
      view.setBigUint64(
        40 + 16 * frames + 8 * i,
        BigInt(29 * 48000 + i * 480),
        true,
      );
    new Uint8Array(buffer, 40 + 16 * frames + 8 * columns).fill(100);
    route.send(Buffer.from(buffer));
  });
  await page.goto("/");
  const plots = page.locator(".plot canvas");
  const ranges = () =>
    plots.evaluateAll((elements) =>
      elements.map((e) => [
        e.getAttribute("data-start-sample"),
        e.getAttribute("data-end-sample"),
        e.getAttribute("data-span-samples"),
      ]),
    );
  const aligned = async () => {
    await expect
      .poll(async () => {
        const values = await ranges();
        return (
          values.length === 2 &&
          JSON.stringify(values[0]) === JSON.stringify(values[1])
        );
      })
      .toBe(true);
  };
  await expect
    .poll(() => plots.first().getAttribute("data-end-sample"))
    .toBe(String(30 * 48000));
  await page
    .getByRole("button", { name: "Zoom in both graphs", exact: true })
    .click();
  await expect
    .poll(() => plots.first().getAttribute("data-span-samples"))
    .toBe(String(6 * 48000));
  await aligned();
  await page
    .getByRole("button", { name: "Scroll both graphs backward" })
    .click();
  await expect
    .poll(() => plots.first().getAttribute("data-end-sample"))
    .toBe(String(27 * 48000));
  await aligned();
  await expect(page.getByLabel("Shared graph time range")).toContainText(
    "history",
  );
  const box = await plots.last().boundingBox();
  if (!box) throw new Error("Missing plot");
  await page.mouse.move(box.x + box.width / 2, box.y + 80);
  await page.mouse.wheel(0, -180);
  await expect
    .poll(async () =>
      Number(await plots.last().getAttribute("data-span-samples")),
    )
    .toBeLessThan(6 * 48000);
  await aligned();
  const end = Number(await plots.first().getAttribute("data-end-sample"));
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 70, box.y + 80, { steps: 5 });
  await page.mouse.up();
  await expect
    .poll(async () =>
      Number(await plots.first().getAttribute("data-end-sample")),
    )
    .toBeLessThan(end);
  await aligned();
  await plots.first().press("Home");
  await expect
    .poll(() => plots.first().getAttribute("data-start-sample"))
    .toBe("0");
  await aligned();
  await page.getByRole("button", { name: "Follow live", exact: true }).click();
  await expect
    .poll(() => plots.first().getAttribute("data-end-sample"))
    .toBe(String(30 * 48000));
  await aligned();
  await expect(page.getByLabel("Shared graph time range")).toContainText(
    "live",
  );
});

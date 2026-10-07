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
    for (const [endpoint, seconds, detail] of [
      ['caller', 20, 'training: Acquiring received modem'],
      ['answerer', 22, 'training: Acquiring received modem'],
      ['caller', 26, 'connected: Ready for actual text'],
      ['answerer', 27, 'connected: Ready for actual text'],
    ] as const) route.send(JSON.stringify({type:'event',generation:1,endpoint,
      sample_index:seconds*48000,event_type:'call_stage_changed',detail}));
    route.send(JSON.stringify({type:'event',generation:1,endpoint:'caller',sample_index:24*48000,
      event_type:'negotiation_message',detail:'V.8 CM transmitted',
      negotiation:{protocol:'V.8',signal:'CM',direction:'tx',raw_hex:'c1 05 12',validation:'valid'}}));
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
  const callerBox = await plots.first().boundingBox();
  if (!callerBox) throw new Error('Missing caller plot');
  const initialRange = await ranges();
  await page.mouse.move(callerBox.x + 36 + (callerBox.width-48)*0.4, callerBox.y+80);
  await expect.poll(async () => {
    const cursors = await plots.evaluateAll(elements => elements.map(el=>el.getAttribute('data-cursor-sample')));
    return cursors[0] !== null && cursors[0] === cursors[1] && Number(cursors[0]) < 30*48000;
  }).toBe(true);
  const hovered = await plots.first().getAttribute('data-cursor-sample');
  await page.mouse.click(callerBox.x + 36 + (callerBox.width-48)*0.4, callerBox.y+80);
  await page.mouse.move(10,10);
  await expect.poll(() => plots.first().getAttribute('data-cursor-sample')).toBe(hovered);
  expect(await ranges()).toEqual(initialRange); // A click pins; it must not pan.
  await page.getByLabel('Shared graph navigation').getByRole('button',{name:'Follow live',exact:true}).click();
  await page.mouse.move(10,10);
  await expect.poll(() => plots.first().getAttribute('data-cursor-sample')).toBe(String(30*48000));
  const callerPhases = page.getByLabel('Caller handshake and negotiation timeline',{exact:true});
  const answererPhases = page.getByLabel('Answerer handshake and negotiation timeline',{exact:true});
  await expect(callerPhases).toContainText('Training');
  await expect(callerPhases).toContainText('Data');
  await callerPhases.getByRole('button',{name:/V\.8 CM at 24\.000/}).click();
  await expect.poll(() => plots.first().getAttribute('data-cursor-sample')).toBe(String(24*48000));
  await expect.poll(() => plots.last().getAttribute('data-cursor-sample')).toBe(String(24*48000));
  await expect(callerPhases).toContainText('Training');
  await expect(answererPhases).toContainText('Training');
  await page.getByLabel('Caller signal view').selectOption('2');
  await expect(callerPhases.getByRole('button',{name:/V\.8 CM at/})).toHaveCount(0);
  await page.getByLabel('Caller signal view').selectOption('0');
  await page.getByLabel('Shared graph navigation').getByRole('button',{name:'Follow live',exact:true}).click();
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
  await page.mouse.move(10,10);
  await expect.poll(() => plots.first().getAttribute('data-cursor-sample')).toBe(String(27*48000));
  await expect.poll(() => plots.last().getAttribute('data-cursor-sample')).toBe(String(27*48000));
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

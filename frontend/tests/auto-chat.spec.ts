import {test, expect} from '@playwright/test';
test('auto chat starts a call, exchanges changing lines, stops and survives restart', async({page}) => {
  await page.goto('/');
  await expect(page.getByText('IDLE · Connected',{exact:true})).toBeVisible();
  await page.getByLabel('Modem profile').selectOption('dqpsk1200');
  await page.getByLabel('Auto chat',{exact:true}).check();
  await expect(page.getByText('LIVE · Connected',{exact:true})).toBeVisible();
  await expect(page.getByLabel('Auto chat status')).toContainText('Waiting for handshake');
  await expect(page.getByLabel('Answerer received text')).toContainText(/\d\d:\d\d #00 A hi [A-Za-z0-9!?+=]{4}/,{timeout:12000});
  await expect(page.getByLabel('Caller received text')).toContainText(/\d\d:\d\d #01 B ok [A-Za-z0-9!?+=]{4}/,{timeout:6000});
  await expect(page.getByLabel('Answerer received text')).toContainText('#02 A hi',{timeout:6000});
  await expect(page.locator('footer')).toContainText('Audio: playing');
  await page.getByLabel('Auto chat',{exact:true}).uncheck();
  // Let the message already in flight finish, then verify no further lines.
  await page.waitForTimeout(1000);
  const caller = await page.getByLabel('Caller received text').innerText();
  const answerer = await page.getByLabel('Answerer received text').innerText();
  await page.waitForTimeout(1300);
  await expect(page.getByLabel('Caller received text')).toHaveText(caller);
  await expect(page.getByLabel('Answerer received text')).toHaveText(answerer);
  await page.getByLabel('Auto chat',{exact:true}).check();
  await page.getByRole('button',{name:'Restart',exact:false}).click();
  await expect(page.getByLabel('Auto chat',{exact:true})).toBeChecked();
  await expect(page.getByLabel('Auto chat status')).toContainText('Waiting for handshake');
  await page.getByRole('button',{name:'Hang up',exact:true}).click();
  await expect(page.getByLabel('Auto chat',{exact:true})).not.toBeChecked();
});

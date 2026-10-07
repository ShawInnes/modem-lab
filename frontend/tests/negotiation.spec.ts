import {test, expect} from '@playwright/test';

test('V.8 menus are visible before real negotiated Auto chat', async ({page}) => {
  test.setTimeout(45000);
  await page.goto('/');
  await expect(page.getByText('IDLE · Connected', {exact: true})).toBeVisible();
  await page.getByLabel('Call setup procedure').selectOption('v8');
  await expect(page.getByLabel('Modem profile')).toHaveValue('qam2400');
  await page.getByText('Device capabilities and examples', {exact: true}).click();
  await expect(page.getByLabel('Caller supports V.22 family')).toBeChecked();
  await page.getByLabel('Auto chat', {exact: true}).check();
  await expect(page.getByLabel('Call setup procedure')).toBeDisabled();
  await expect(page.getByLabel('Answerer received text')).toContainText('#00 A hi', {timeout: 25000});
  await expect(page.getByLabel('Caller received text')).toContainText('#01 B ok', {timeout: 7000});
  const events = page.getByLabel('Negotiation events', {exact: true});
  await expect(events).toContainText('ANSam');
  await expect(events).toContainText('CM');
  await expect(events).toContainText('JM');
  await expect(events).toContainText('CJ');
  await events.getByRole('button').filter({hasText: /CM.*rx/}).first().click();
  await expect(page.getByLabel('Selected negotiation message')).toContainText('Received');
  await expect(page.getByLabel('Selected negotiation message')).toContainText('Raw octets');
  await page.getByRole('button', {name: 'Hang up', exact: true}).click();
  await expect(page.getByLabel('Call setup procedure')).toBeEnabled();
});

test('V.8bis capability request and acknowledgement precede V.8', async ({page}) => {
  test.setTimeout(50000);
  await page.goto('/');
  await expect(page.getByText('IDLE · Connected', {exact: true})).toBeVisible();
  await page.getByLabel('Call setup procedure').selectOption('v8bis');
  await page.getByText('Device capabilities and examples', {exact: true}).click();
  await expect(page.getByLabel('Answerer supports V.8bis')).toBeChecked();
  await page.getByLabel('Auto chat', {exact: true}).check();
  await expect(page.getByLabel('Answerer received text')).toContainText('#00 A hi', {timeout: 35000});
  const events = page.getByLabel('Negotiation events', {exact: true});
  await expect(events).toContainText('CR');
  await expect(events).toContainText('CL');
  await expect(events).toContainText('MS');
  await expect(events).toContainText('ACK');
  await expect(events).toContainText('CM');
  await page.getByRole('button', {name: 'Hang up', exact: true}).click();
});

test('no common family fails without decoded payload', async ({page}) => {
  test.setTimeout(35000);
  await page.goto('/');
  await expect(page.getByText('IDLE · Connected', {exact: true})).toBeVisible();
  await page.getByLabel('Call setup procedure').selectOption('v8');
  await page.getByText('Device capabilities and examples', {exact: true}).click();
  await page.getByRole('button', {name: 'Answerer offers no common family', exact: true}).click();
  await expect(page.getByLabel('Answerer supports V.22 family')).not.toBeChecked();
  await page.getByLabel('Auto chat', {exact: true}).check();
  await expect(page.getByLabel('Call progress')).toContainText('failed', {timeout: 25000});
  await expect(page.getByLabel('Answerer received text')).toContainText('Waiting for decoded text');
  await expect(page.getByLabel('Negotiation inspector')).toContainText(/no common|incompatible|unsupported/i);
  await page.getByRole('button', {name: 'Hang up', exact: true}).click();
});

test('answerer can initiate the V.8bis request independently of telephone role', async ({page}) => {
  test.setTimeout(50000);
  await page.goto('/');
  await expect(page.getByText('IDLE · Connected', {exact: true})).toBeVisible();
  await page.getByLabel('Call setup procedure').selectOption('v8bis');
  await expect(page.getByLabel('V.8bis initiator')).toBeVisible();
  await page.getByLabel('V.8bis initiator').selectOption('answerer');
  await expect(page.getByLabel('V.8bis initiator')).toHaveValue('answerer');
  await page.getByLabel('Auto chat', {exact: true}).check();
  await expect(page.getByLabel('Answerer received text')).toContainText('#00 A hi', {timeout: 35000});
  await expect(page.getByLabel('Negotiation events', {exact: true}).getByRole('button').filter({hasText: /Answerer.*CRd.*tx/})).toBeVisible();
  await page.getByRole('button', {name: 'Hang up', exact: true}).click();
});

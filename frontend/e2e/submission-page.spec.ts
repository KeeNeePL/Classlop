import { expect, test } from '@playwright/test';

// Damian R. on Zbiory liczbowe in 1A: past its due time, so the Teacher can change it.
const PAGE = '/klasy/1a/prace/1a-0/1a-3';

test('overriding one Item changes the total, here and on the Assignment page', async ({ page }) => {
  await page.goto(PAGE);
  await expect(page.getByRole('heading', { name: 'Damian R.' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Skąd te dane?' })).toBeVisible();
  // The bank's Items of sections I and II, both closed, 1 point.
  await expect(page.getByRole('article', { name: /^Zadanie \d$/ })).toHaveCount(2);
  await expect(page.getByText('Ile to')).toBeVisible();

  const total = page.getByLabel('Suma punktów');
  const points = page.getByLabel('Punkty za zadanie 1');
  const before = Number((await total.locator('b').textContent()) ?? '');
  const was = Number(await points.inputValue());
  const now = was === 0 ? 1 : 0;

  await points.fill(String(now));
  await points.press('Enter');
  await points.blur();

  await expect(total.locator('b')).toHaveText(String(before - was + now));
  await expect(page.getByText('zmienione przez ciebie')).toBeVisible();

  await page.getByRole('link', { name: /← Zbiory liczbowe/ }).click();
  const row = page.getByRole('row').filter({ hasText: 'Damian R.' });
  await expect(row).toContainText(`${before - was + now}/2`);
});

test('a fixed Transcription renders its maths, and its markup as plain text', async ({ page }) => {
  await page.goto(PAGE);
  const second = page.getByRole('article', { name: 'Zadanie 2' });

  await second.getByRole('button', { name: 'Popraw odczyt' }).click();
  await second.getByLabel('Poprawiony odczyt').fill('<b>8a</b> czyli $8a$');
  await second.getByRole('button', { name: 'Oceń zadanie ponownie' }).click();

  await expect(second.getByText('(poprawiony)')).toBeVisible();
  await expect(second.getByText('<b>8a</b> czyli')).toBeVisible();
  await expect(second.locator('.work .katex')).toHaveCount(1);
  await expect(second.locator('.work b')).toHaveCount(0);
});

test('previous and next move between Submissions without going back', async ({ page }) => {
  await page.goto(PAGE);
  const next = page.locator('a[rel="next"]');
  const name = ((await next.textContent()) ?? '').replace('→', '').trim();

  await next.click();

  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  await expect(page.locator('a[rel="prev"]')).toContainText('Damian R.');
});

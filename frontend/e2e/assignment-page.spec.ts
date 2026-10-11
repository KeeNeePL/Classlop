import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';

test('an Assignment opens from the Class overview, shows its summary and downloads as CSV', async ({
  page,
}) => {
  await page.goto('/klasy/2c');
  await page.getByRole('link', { name: /^Równania, zadana .*, Ocenione$/ }).click();

  await expect(page).toHaveURL('/klasy/2c/prace/2c-2');
  await expect(page.getByRole('heading', { name: 'Równania' })).toBeVisible();
  await expect(page.getByText('ZMYŚLONE')).toBeVisible();

  // Closed and handed in: nothing changes any more.
  for (const name of ['Zmień termin', 'Dodaj uczniów', 'Usuń pracę']) {
    await expect(page.getByRole('button', { name })).toBeDisabled();
  }

  await expect(page.getByRole('heading', { name: 'Podsumowanie' })).toBeVisible();
  await expect(page.getByText('Średnia', { exact: true })).toBeVisible();
  await expect(
    page.getByRole('list', { name: 'Rozkład wyników' }).getByRole('listitem'),
  ).toHaveCount(10);

  const items = page.getByRole('list', { name: 'Zadania' });
  await expect(items.getByText('Zadanie 1')).toBeVisible();
  await expect(items.getByText(/\(\d+ prac\)/).first()).toBeVisible();

  // Held Submissions come first and wait for the Teacher, with no points yet.
  const rows = page.getByRole('row');
  await expect(rows).toHaveCount(9);
  await expect(rows.nth(1)).toContainText('czeka na sprawdzenie');
  await expect(page.getByRole('row').filter({ hasText: 'brak pracy' })).toHaveCount(1);

  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Pobierz CSV' }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe('Równania (2C).csv');
  const csv = (await readFile(await file.path(), 'utf8')).replace(/^\uFEFF/, '');
  const lines = csv.trim().split('\r\n');
  expect(lines[0]).toBe('Uczeń;Punkty;Maks.;Procent;Proponowana ocena;Stan;Spóźniona');
  expect(lines).toHaveLength(9);
  expect(csv).toContain('czeka na sprawdzenie');
});

test('an open Assignment shows hand-ins only and can still change', async ({ page }) => {
  await page.goto('/klasy/2c/prace/2c-4');

  await expect(page.getByRole('heading', { name: 'Funkcje' })).toBeVisible();
  await expect(page.getByText(/Wyniki pojawią się w terminie oddania/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Zmień termin' })).toBeEnabled();

  await page.getByRole('button', { name: 'Zmień termin' }).click();
  await expect(page.getByLabel('Termin oddania')).toHaveValue(/^\d{4}-\d\d-\d\dT\d\d:\d\d$/);
});

test('an Assignment that is not there says so', async ({ page }) => {
  await page.goto('/klasy/2c/prace/usunieta');

  await expect(page.getByRole('heading', { name: 'Nie ma takiej pracy' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Wróć do klasy' })).toHaveAttribute(
    'href',
    '/klasy/2c',
  );
});

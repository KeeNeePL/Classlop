import { expect, test } from '@playwright/test';

const day = (offset: number) => {
  const d = new Date(Date.now() + offset * 86_400_000);
  return d.toISOString().slice(0, 10);
};

test('a Student report opens from the Class and follows the chosen period', async ({ page }) => {
  await page.goto('/klasy/2c');
  await page.getByRole('link', { name: 'Uczniowie', exact: true }).click();
  await page
    .getByRole('table', { name: 'Uczniowie' })
    .getByRole('link', { name: 'Ala K.' })
    .click();

  await expect(page).toHaveURL('/klasy/2c/uczniowie/2c-0');
  await expect(page.getByRole('heading', { name: 'Ala K.' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Skąd te dane?' })).toBeVisible();
  await expect(page.getByText('Frekwencja')).toBeVisible();
  await expect(page.getByRole('img', { name: /na tle średniej klasy/ })).toBeVisible();
  const rows = page.locator('tbody tr');
  await expect(rows).toHaveCount(5);

  // The last fortnight leaves the older Assignments out.
  await page.getByRole('radio', { name: 'Własny' }).click();
  await page.locator('input[type="date"]').first().fill(day(-14));
  await expect(rows).toHaveCount(3);

  await page.getByRole('radio', { name: 'Sprawdziany' }).click();
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText('Sprawdzian');
});

test('a Note is kept, and the thresholds on Ustawienia change the Suggested grades', async ({
  page,
}) => {
  await page.request.post('/api/e2e/reset');
  await page.goto('/klasy/2c/uczniowie/2c-3');
  await page.getByLabel('Notatka').fill('Poprawił kartkówkę z funkcji.');
  await page.getByRole('button', { name: 'Zapisz notatkę' }).click();
  await expect(page.getByRole('status')).toHaveText('Zapisano.');
  await page.reload();
  await expect(page.getByLabel('Notatka')).toHaveValue('Poprawił kartkówkę z funkcji.');

  await page.goto('/ustawienia');
  const inputs = page.locator('input[type="number"]');
  await expect(inputs.first()).toHaveValue('30');
  for (const [i, v] of ['1', '2', '3', '4', '5'].entries()) await inputs.nth(i).fill(v);
  await page.getByRole('button', { name: 'Zapisz progi' }).click();
  await expect(page.getByRole('status')).toHaveText('Zapisano.');

  await page.goto('/klasy/2c/uczniowie/2c-3');
  const graded = page.locator('tbody tr').filter({ hasText: 'pkt' });
  for (const cell of await graded.locator('td.grade').all()) await expect(cell).toHaveText('6');
  await page.request.post('/api/e2e/reset');
});

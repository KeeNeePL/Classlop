import { expect, test } from '@playwright/test';

test('the Uczniowie tab lists the Class, searches, sorts and opens a Student report', async ({
  page,
}) => {
  await page.goto('/klasy/2c');
  await page.getByRole('link', { name: 'Uczniowie', exact: true }).click();

  await expect(page).toHaveURL('/klasy/2c/uczniowie');
  const table = page.getByRole('table', { name: 'Uczniowie' });
  const rows = table.locator('tbody tr');
  await expect(rows).toHaveCount(8);
  await expect(table.getByText('były uczeń')).toBeVisible();
  await expect(rows.first()).toContainText('Ala K.');

  // Highest result first; the weak first Student goes to the bottom.
  await page.getByRole('button', { name: /^Wynik/ }).click();
  await expect(page).toHaveURL(/sort=-wynik/);
  await expect(rows.last()).toContainText('Ala K.');

  await page.getByLabel('Szukaj ucznia').fill('ce');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText('Celina P.');

  await rows.first().getByRole('link', { name: 'Celina P.' }).click();
  await expect(page).toHaveURL('/klasy/2c/uczniowie/2c-2');

  // Back keeps the search and the sort.
  await page.goBack();
  await expect(page.getByLabel('Szukaj ucznia')).toHaveValue('ce');
  await expect(page).toHaveURL(/sort=-wynik/);
});

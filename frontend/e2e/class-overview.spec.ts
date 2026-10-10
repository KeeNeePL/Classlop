import { expect, test } from '@playwright/test';

test('a Class opens on its Przegląd tab and shows its Progress', async ({ page }) => {
  await page.goto('/klasy/2c');

  await expect(page.getByRole('heading', { name: 'Klasa 2C' })).toBeVisible();
  await expect(page.getByText('ZMYŚLONE')).toBeVisible();

  await expect(page.getByRole('heading', { name: 'Postęp' })).toBeVisible();
  await expect(page.getByText('Liczby rzeczywiste')).toBeVisible();
  await expect(page.getByText(/^\d+% z \d+ pkt$/).first()).toBeVisible();
  await expect(page.getByText('brak danych').first()).toBeVisible();

  const hint = page.getByRole('button', { name: 'Co to znaczy?' }).first();
  await expect(page.getByRole('tooltip').first()).toBeHidden();
  await hint.hover();
  await expect(page.getByRole('tooltip').first()).toContainText('Punkty zdobyte podzielone przez');

  await page.getByRole('tab', { name: 'Tematy' }).click();
  await expect(page.getByText('Wykonuje działania').first()).toBeVisible();

  await expect(page.getByRole('img', { name: /^Średnia klasy: / })).toBeVisible();
  await expect(page.locator('cl-line-chart canvas')).toBeVisible();
  await expect(page.getByRole('row', { name: /Zbiory liczbowe/ })).toBeVisible();

  const attention = page.getByRole('list', { name: 'Wymagają uwagi' }).getByRole('listitem');
  await expect(attention.first()).toContainText('Wynik');

  await expect(page.getByRole('list', { name: 'Uczniowie' }).getByRole('listitem')).toHaveCount(8);
  await expect(page.getByRole('list', { name: 'Uczniowie' }).getByText('były uczeń')).toBeVisible();
});

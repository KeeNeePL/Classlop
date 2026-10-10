import { expect, test } from '@playwright/test';

test('a Class opens on its Przegląd tab and shows its Progress', async ({ page }) => {
  await page.goto('/klasy/2c');

  await expect(page.getByRole('heading', { name: 'Klasa 2C' })).toBeVisible();
  await expect(page.getByText('ZMYŚLONE')).toBeVisible();

  await expect(page.getByRole('heading', { name: 'Postęp' })).toBeVisible();
  await expect(page.getByText('Liczby rzeczywiste')).toBeVisible();
  for (const kind of ['Kartkówki', 'Sprawdziany', 'Prace domowe']) {
    await expect(page.getByText(kind, { exact: true })).toBeVisible();
  }
  await expect(page.getByText('Średnia', { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/^\d+%$/).first()).toBeVisible();
  await expect(page.getByText(/pkt/)).toHaveCount(0);
  await expect(page.getByText('brak danych', { exact: true }).first()).toBeVisible();

  const hint = page.getByRole('button', { name: 'Co to znaczy?' }).first();
  await expect(page.getByRole('tooltip').first()).toBeHidden();
  await hint.hover();
  await expect(page.getByRole('tooltip').first()).toContainText('Procent punktów zdobytych');

  await page.getByRole('tab', { name: 'Tematy' }).click();
  await expect(page.getByText('Wykonuje działania').first()).toBeVisible();

  for (const lane of ['Sprawdzian', 'Kartkówka', 'Praca domowa']) {
    await expect(page.getByRole('list', { name: lane })).toBeVisible();
  }
  const funkcje = page.getByRole('button', { name: /^Funkcje, zadana .*, Zbieranie prac$/ });
  await expect(page.getByRole('button', { name: /^Równania, zadana .*, Ocenione$/ })).toBeVisible();
  await funkcje.hover();
  await expect(page.getByRole('tooltip').filter({ hasText: 'Funkcje' })).toContainText(
    'oddane 5/8',
  );

  const attention = page.getByRole('list', { name: 'Wymagają uwagi' }).getByRole('listitem');
  await expect(attention.first()).toContainText('Wynik');

  await expect(page.getByRole('list', { name: 'Uczniowie' }).getByRole('listitem')).toHaveCount(8);
  await expect(page.getByRole('list', { name: 'Uczniowie' }).getByText('były uczeń')).toBeVisible();
});

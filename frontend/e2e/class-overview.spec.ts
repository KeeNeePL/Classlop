import { expect, test } from '@playwright/test';

test('a Class opens on its Przegląd tab and shows its Progress', async ({ page }) => {
  await page.goto('/klasy/2c');

  await expect(page.getByRole('heading', { name: 'Klasa 2C' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Skąd te dane?' })).toBeVisible();

  await expect(page.getByRole('heading', { name: 'Postęp' })).toBeVisible();
  // Folded: the four sections with the newest graded work; the oldest, Liczby rzeczywiste, waits.
  const progress = page.locator('cl-panel').first();
  await expect(progress.getByText('Układy równań', { exact: true })).toBeVisible();
  await expect(progress.getByText('Liczby rzeczywiste')).toHaveCount(0);
  for (const kind of ['Kartkówki', 'Sprawdziany', 'Prace domowe']) {
    await expect(page.getByText(kind, { exact: true })).toBeVisible();
  }
  await expect(page.getByText('Średnia', { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/^\d+%$/).first()).toBeVisible();
  await expect(page.getByText(/pkt/)).toHaveCount(0);

  const hint = page.getByRole('button', { name: 'Co to znaczy?' }).first();
  await expect(page.getByRole('tooltip').first()).toBeHidden();
  await hint.hover();
  await expect(page.getByRole('tooltip').first()).toContainText('Procent punktów zdobytych');
  await page.mouse.move(0, 0);

  await expect(page.getByText('Stereometria')).toHaveCount(0);
  await page.getByRole('button', { name: 'Rozwiń wszystkie działy' }).click();
  await expect(page.getByText('Stereometria')).toBeVisible();
  await expect(page.getByText('Liczby rzeczywiste')).toBeVisible();
  await expect(page.getByText('brak danych', { exact: true }).first()).toBeVisible();
  await expect(progress.getByText('—', { exact: true }).first()).toBeVisible();

  await page.getByRole('tab', { name: 'Tematy' }).click();
  await expect(page.getByText('Wykonuje działania').first()).toBeVisible();

  for (const lane of ['Sprawdzian', 'Kartkówka', 'Praca domowa']) {
    await expect(page.getByRole('list', { name: lane })).toBeVisible();
  }
  const funkcje = page.getByRole('link', { name: /^Funkcje, zadana .*, Zbieranie prac$/ });
  // Closed, with Submissions still Held for the Teacher: closed, not graded.
  const equations = await (await page.request.get('/api/classes/2c/assignments/2c-2')).json();
  expect([equations.title, equations.state, equations.counts.held > 0]).toEqual([
    'Równania',
    'closed',
    true,
  ]);
  await expect(page.getByRole('link', { name: /^Równania, zadana .*, Zamknięta$/ })).toBeVisible();
  await expect(page.getByRole('list', { name: 'Legenda' })).not.toContainText('Ocenione');
  await funkcje.hover();
  await expect(page.getByRole('tooltip').filter({ hasText: 'Funkcje' })).toContainText(
    /oddane \d+\/8/,
  );

  const attention = page.getByRole('list', { name: 'Wymagają uwagi' }).getByRole('listitem');
  await expect(attention.first()).toContainText('Wynik');
});

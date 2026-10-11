import { expect, test } from '@playwright/test';

// The bank is shared by every test on the server; a test that changes it puts it back.
test.afterEach(({ request }) => request.post('/api/e2e/reset'));

const items = (page: import('@playwright/test').Page) =>
  page.getByRole('list', { name: 'Zadania' }).getByRole('listitem');

test('the Teacher searches the bank and opens an Item', async ({ page }) => {
  await page.goto('/bank');

  await expect(page.getByRole('heading', { level: 1, name: 'Bank zadań' })).toBeVisible();
  await expect(page.getByText('Wybierz zadanie z listy.')).toBeVisible();
  // Retired Items stay out of the list.
  await expect(items(page)).toHaveCount(7);
  await expect(page.getByText('Znaleziono: 7')).toBeVisible();

  await page.getByRole('searchbox', { name: 'Szukaj zadań' }).fill('równanie');
  await expect(items(page)).toHaveCount(1);
  await items(page).getByRole('link').click();

  await expect(page).toHaveURL(/\/bank\/[0-9a-f-]{36}$/);
  await expect(page.getByText('Rozwiąż równanie')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Rozwiązanie wzorcowe' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Kryteria oceniania' })).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Oba pierwiastki.' })).toBeVisible();
  await expect(
    page.locator('dd').filter({ hasText: 'Rozwiązuje równania i nierówności' }),
  ).toBeVisible();
  // The mathematics goes through KaTeX.
  await expect(page.locator('.detail .katex').first()).toBeVisible();

  const usage = page.getByRole('heading', { name: 'Historia użycia' }).locator('..');
  await expect(usage.getByRole('row', { name: /Funkcja kwadratowa\s+2C.*72%/ })).toBeVisible();
});

test('the filters narrow the list, and Retired items are shown only when asked for', async ({
  page,
}) => {
  await page.goto('/bank');
  await expect(items(page)).toHaveCount(7);

  await page.getByRole('button', { name: 'trudne' }).click();
  await expect(items(page)).toHaveCount(2);
  await page.getByRole('button', { name: 'trudne' }).click();

  await page.getByLabel('Nie zadane klasie').selectOption({ label: '2C' });
  await expect(items(page)).toHaveCount(6);
  await page.getByLabel('Nie zadane klasie').selectOption({ label: 'dowolnej' });

  await page.getByLabel('Tylko do sprawdzenia').check();
  await expect(items(page)).toHaveCount(4);
  await page.getByLabel('Tylko do sprawdzenia').uncheck();

  await page.getByLabel('Pokaż wycofane').check();
  await expect(items(page)).toHaveCount(8);
  await expect(items(page).filter({ hasText: 'wycofane' })).toHaveCount(1);

  await page.getByText('Tematy z podstawy programowej').click();
  await page.getByRole('button', { name: 'Funkcje', exact: true }).click();
  await expect(items(page)).toHaveCount(1);
});

test('Retire and Restore move an Item out of the list and back', async ({ page }) => {
  await page.goto('/bank');
  await page.getByRole('searchbox', { name: 'Szukaj zadań' }).fill('układ równań');
  await expect(items(page)).toHaveCount(1);
  await items(page).getByRole('link').click();

  await page.getByRole('button', { name: 'Wycofaj' }).click();
  await expect(page.getByText('wycofane').first()).toBeVisible();
  await expect(items(page)).toHaveCount(0);

  await page.getByRole('button', { name: 'Przywróć' }).click();
  await expect(page.getByRole('button', { name: 'Wycofaj' })).toBeVisible();
  await expect(items(page)).toHaveCount(1);
});

test('dismissing a flag lowers the count in the sidebar', async ({ page }) => {
  await page.goto('/bank');
  const link = page.getByRole('navigation').getByRole('link', { name: /^Bank zadań/ });
  await expect(link).toHaveText(/4$/);

  await page.getByLabel('Tylko do sprawdzenia').check();
  await items(page).first().getByRole('link').click();
  await expect(page.getByText('Do sprawdzenia.')).toBeVisible();
  await page.getByRole('button', { name: 'Odrzuć flagę' }).click();

  await expect(page.getByText('Do sprawdzenia.')).toHaveCount(0);
  await expect(link).toHaveText(/3$/);
  await expect(items(page)).toHaveCount(3);
});

test('an edit saves a new version and the AI offers a new solution', async ({ page }) => {
  await page.goto('/bank');
  await page.getByRole('searchbox', { name: 'Szukaj zadań' }).fill('równanie');
  await expect(items(page)).toHaveCount(1);
  await items(page).getByRole('link').click();

  await page.getByRole('button', { name: 'Edytuj' }).click();
  await page.getByLabel('Treść').fill('Rozwiąż równanie $x^2 = 9$.');
  await page.getByRole('button', { name: 'Zapisz' }).click();

  await expect(page.getByText('wersja 2')).toBeVisible();
  await expect(page.getByText('Zadanie zmieniono.')).toBeVisible();
  await expect(
    page.getByText('Rozwiązanie wzorcowe mogło przestać do niego pasować.'),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Nie teraz' }).click();
  await expect(page.getByText('Zadanie zmieniono.')).toHaveCount(0);

  await page.getByRole('button', { name: 'Edytuj' }).click();
  await page.getByLabel('Punkty', { exact: true }).fill('1');
  await page.getByRole('button', { name: 'Zapisz' }).click();
  await expect(page.getByRole('alert')).toContainText('Rubric');
  await page.getByRole('button', { name: 'Anuluj' }).click();
  await expect(page.getByText('wersja 2')).toBeVisible();
});

test('a closed Item has its options and the right one marked', async ({ page }) => {
  await page.goto('/bank');
  await page.getByRole('searchbox', { name: 'Szukaj zadań' }).fill('Ile to');
  await expect(items(page)).toHaveCount(1);
  await items(page).getByRole('link').click();

  await expect(page.getByRole('heading', { name: 'Rozwiązanie wzorcowe' })).toHaveCount(0);
  await expect(page.getByText('poprawna')).toHaveCount(1);
});

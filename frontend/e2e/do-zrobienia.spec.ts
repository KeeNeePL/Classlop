import { expect, test } from '@playwright/test';

test('Do zrobienia opens with the sidebar and its queue, badged as invented', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Do zrobienia' })).toBeVisible();
  await expect(
    page.getByRole('list', { name: 'Do zrobienia' }).getByRole('listitem').locator('.title'),
  ).toHaveText([
    'Trwa lekcja: klasa 1A',
    'Zaloguj się ponownie',
    'Nie udało się wydać pracy «Ciągi: zadania z treścią»',
    'Zespół klasy 3B usunięto w Teams',
    'Ocenione przez AI: Funkcja kwadratowa (2C)',
    'Ocenione przez AI: Graniastosłupy (3B)',
    '12:50 lekcja: klasa 3B',
    'Termin dziś 20:00: Wzory skróconego mnożenia (1A)',
  ]);
  await expect(page.getByText('ZMYŚLONE').first()).toBeVisible();

  const sidebar = page.getByRole('navigation');
  await expect(sidebar.getByRole('link', { name: /^Do zrobienia\s*8$/ })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: 'Classlop AI' })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: /^Bank zadań\s*4$/ })).toBeVisible();
  for (const name of ['1A', '2C', '3B']) {
    await expect(sidebar.getByRole('link', { name: new RegExp(`^Klasa ${name}`) })).toBeVisible();
  }
  await expect(sidebar.getByRole('link', { name: '+ Nowa klasa' })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: 'Ustawienia' })).toBeVisible();
});

const routes = [
  ['/ai', 'Classlop AI'],
  ['/ai/pierwszy-czat', 'Classlop AI'],
  ['/bank', 'Bank zadań'],
  ['/bank/zadanie-1', 'Bank zadań'],
  ['/klasy/nowa', 'Nowa klasa'],
  ['/klasy/1a', 'Klasa 1A'],
  ['/klasy/1a/lekcje', 'Klasa 1A'],
  ['/klasy/1a/lekcje/wzory', 'Klasa 1A'],
  ['/klasy/1a/ustawienia', 'Klasa 1A'],
  ['/klasy/1a/uczniowie/ala-k', 'Uczeń'],
  ['/klasy/1a/nowa-praca', 'Nowa praca'],
  ['/klasy/1a/prace/wzory', 'Praca'],
  ['/klasy/1a/prace/wzory/ala-k', 'Praca ucznia'],
  ['/ustawienia', 'Ustawienia'],
] as const;

for (const [path, heading] of routes) {
  test(`${path} resolves`, async ({ page }) => {
    await page.goto(path);

    await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible();
  });
}

test('an unknown route says there is no such page', async ({ page }) => {
  await page.goto('/klasy/1a/nie-ma-takiej');

  await expect(page.getByRole('heading', { name: 'Nie ma takiej strony' })).toBeVisible();
});

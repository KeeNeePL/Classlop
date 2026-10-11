import { expect, test } from '@playwright/test';

// The tenant is FakeTeams, shared by every test on the server; a test that changes it puts it back.
test.afterEach(({ request }) => request.post('/api/e2e/reset'));

test('the Teacher creates a Class, manages its Students and deletes it', async ({ page }) => {
  await page.goto('/');
  const sidebar = page.getByRole('navigation');
  await sidebar.getByRole('link', { name: '+ Nowa klasa' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Nowa klasa' })).toBeVisible();

  await page.getByLabel('Nazwa klasy').fill('4D');
  await page.getByRole('searchbox', { name: 'Szukaj ucznia' }).fill('Karolina');
  await page.getByRole('button', { name: 'Dodaj: Karolina Mazur' }).click();
  await expect(page.getByRole('list', { name: 'Wybrani uczniowie' })).toContainText(
    'Karolina Mazur',
  );
  await page.getByRole('button', { name: 'Utwórz klasę' }).click();

  await expect(page).toHaveURL(/\/klasy\/[0-9A-Z]{26}$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Klasa 4D' })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: 'Klasa 4D' })).toBeVisible();

  await page.getByRole('link', { name: 'Ustawienia klasy' }).click();
  const members = page.getByRole('list', { name: 'Uczniowie klasy' });
  await expect(members).toContainText('Karolina Mazur');

  await page.getByRole('searchbox', { name: 'Szukaj ucznia' }).fill('Kaminski');
  await page.getByRole('button', { name: 'Dodaj: Jan Kaminski' }).click();
  await expect(members.getByRole('listitem')).toHaveCount(2);

  await page.getByRole('button', { name: 'Usuń ucznia: Karolina Mazur' }).click();
  const karolina = members.getByRole('listitem').filter({ hasText: 'Karolina Mazur' });
  await expect(karolina).toContainText('były uczeń');
  await expect(karolina.getByRole('button')).toHaveCount(0);

  await page.getByRole('textbox', { name: 'Nazwa klasy' }).fill('4E');
  await page.getByRole('button', { name: 'Zapisz nazwę' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Klasa 4E' })).toBeVisible();
  await expect(sidebar.getByRole('link', { name: 'Klasa 4E' })).toBeVisible();

  // Deleting needs the Class name typed.
  const confirm = page.getByRole('textbox', { name: 'Wpisz nazwę klasy, aby potwierdzić' });
  const remove = page.getByRole('button', { name: 'Usuń klasę' });
  await expect(remove).toBeDisabled();
  await confirm.fill('4D');
  await expect(remove).toBeDisabled();
  await confirm.fill('4E');
  await remove.click();

  await expect(page).toHaveURL('/');
  await expect(sidebar.getByRole('link', { name: 'Klasa 4E' })).toHaveCount(0);
});

test('the Teacher links a team they own as a Class', async ({ page }) => {
  await page.goto('/klasy/nowa');

  await page.getByRole('button', { name: 'Połącz zespół: Klasa 2A matematyka' }).click();

  await expect(page.getByRole('heading', { level: 1, name: 'Klasa 2A matematyka' })).toBeVisible();
  await page.getByRole('link', { name: 'Ustawienia klasy' }).click();
  await expect(page.getByRole('list', { name: 'Uczniowie klasy' })).toContainText('Jan Kowalski');

  // The team is a Class now, so it is not offered again.
  await page.goto('/klasy/nowa');
  await expect(
    page.getByRole('button', { name: 'Połącz zespół: Klasa 3B matematyka' }),
  ).toBeVisible();
  await expect(
    page.getByRole('button', { name: 'Połącz zespół: Klasa 2A matematyka' }),
  ).toHaveCount(0);
});

import { expect, test } from '@playwright/test';

// The server's fake Chat and the bank are shared by every test; a test that changes them puts them
// back.
test.afterEach(({ request }) => request.post('/api/e2e/reset'));

test('the Teacher asks for Items and follows the job in the results panel', async ({ page }) => {
  await page.goto('/ai');
  await expect(page.getByRole('heading', { level: 1, name: 'Classlop AI' })).toBeVisible();
  const panel = page.getByRole('complementary', { name: 'Wyniki czatu' });
  await expect(panel.getByText('Zadania pojawią się tutaj')).toBeVisible();

  // A request that is not clear is answered with a question.
  await page.getByLabel('Wiadomość').fill('Potrzebuję zadań z równań');
  await page.getByRole('button', { name: 'Wyślij' }).click();
  await expect(page).toHaveURL(/\/ai\/[0-9A-Za-z]+$/);
  const log = page.getByRole('log', { name: 'Wiadomości' });
  await expect(log.getByText('Ile zadań, jakiej trudności i w jakim formacie?')).toBeVisible();
  const menu = page.getByRole('button', { name: /^Czat:/ });
  await expect(menu).toHaveAccessibleName(/Potrzebuję zadań z równań/);

  // "Wygeneruj zadania" starts a Generation request in the box.
  await page.getByRole('button', { name: 'Wygeneruj zadania' }).click();
  await expect(page.getByLabel('Wiadomość')).toBeFocused();
  await expect(page.getByLabel('Wiadomość')).toHaveValue(/^Wygeneruj /);
  await page.getByLabel('Wiadomość').fill('Wygeneruj 3 łatwe zadania zamknięte');
  await page.getByRole('button', { name: 'Wyślij' }).click();
  await expect(log.getByText('Zaczynam generować 3 zadania.')).toBeVisible();

  // The conversation carries a chip, and the panel follows the job on the event stream.
  const chip = log.getByRole('group', { name: 'Generowanie zadań' });
  const progress = panel.getByRole('region', { name: 'W toku' });
  await expect(progress.getByText(/Pisanie zadań \(\d z 3\)/)).toBeVisible();
  await expect(chip).toContainText('W toku');
  await expect(page.getByLabel('Trwające zadania: 1')).toBeVisible();
  await expect(chip).toContainText('Gotowe, 3 zadania', { timeout: 15_000 });
  await expect(progress).toHaveCount(0);
  await expect(page.getByLabel('Trwające zadania: 1')).toHaveCount(0);
  const added = panel.getByRole('list', { name: 'Zadania z tego czatu' }).getByRole('listitem');
  await expect(added).toHaveCount(3);
  await expect(added.first().getByText('Zadanie 1')).toBeVisible();
  await expect(log.getByText('Rozwiąż')).toHaveCount(0);

  // Details open in the panel, and retire asks first, then takes the Item out of the bank.
  await added.first().getByText('Szczegóły').click();
  await expect(added.first().getByText('Rozwiązanie wzorcowe:')).toBeVisible();
  await added.first().getByRole('button', { name: 'Usuń zadanie 1' }).click();
  await expect(added.first().getByText('Usunąć to zadanie?')).toBeVisible();
  await added.first().getByRole('button', { name: 'Anuluj' }).click();
  await expect(added.first().getByText('usunięte')).toHaveCount(0);
  await added.first().getByRole('button', { name: 'Usuń zadanie 1' }).click();
  await added.first().getByRole('button', { name: 'Tak, usuń' }).click();
  await expect(added.first().getByText('usunięte')).toBeVisible();

  // Leaving and coming back shows the history and the Items.
  await page.getByRole('link', { name: 'Bank zadań' }).click();
  await page.getByRole('link', { name: 'Classlop AI', exact: true }).click();
  await menu.click();
  await page.getByRole('link', { name: /Potrzebuję zadań/ }).click();
  await expect(log.getByText('Zaczynam generować 3 zadania.')).toBeVisible();
  await expect(added).toHaveCount(3);
});

test('a file starts an upload and a near-duplicate waits for the Teacher', async ({ page }) => {
  await page.goto('/ai');
  await page.locator('input[type=file]').setInputFiles({
    name: 'zestaw.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4'),
  });
  await expect(page.getByText('Plik: zestaw.pdf')).toBeVisible();
  await page.getByRole('button', { name: 'Wyślij' }).click();

  const log = page.getByRole('log', { name: 'Wiadomości' });
  const panel = page.getByRole('complementary', { name: 'Wyniki czatu' });
  const decision = panel.getByRole('region', { name: 'Czeka na Twoją decyzję' });
  const similar = decision.getByRole('list', { name: 'Podobne zadania' });
  await expect(similar).toBeVisible({ timeout: 15_000 });
  await expect(log.getByRole('group', { name: 'Plik zestaw.pdf' })).toContainText(
    'Gotowe, 1 zadanie',
  );
  await expect(
    panel.getByRole('list', { name: 'Zadania z tego czatu' }).getByRole('listitem'),
  ).toHaveCount(1);

  await similar.getByRole('button', { name: 'Pomiń' }).click();
  await expect(decision).toHaveCount(0);
});

test('chats are searched, renamed and deleted in the Chat menu', async ({ page }) => {
  await page.goto('/ai');
  const menu = page.getByRole('button', { name: /^Czat:/ });
  const list = page.getByRole('list', { name: 'Lista czatów' });
  await expect(menu).toHaveAccessibleName('Czat: Nowy czat');
  for (const text of ['Nierówności', 'Ciągi']) {
    await page.getByLabel('Wiadomość').fill(text);
    await page.getByRole('button', { name: 'Wyślij' }).click();
    await expect(menu).toHaveAccessibleName(`Czat: ${text}`);
    await menu.click();
    await page.getByRole('link', { name: '+ Nowy czat' }).click();
    await expect(list).toBeHidden();
    await expect(page.getByText('Napisz, jakich zadań potrzebujesz')).toBeVisible();
  }

  await menu.click();
  await expect(list.getByRole('listitem')).toHaveCount(2);
  await page.getByRole('searchbox', { name: 'Szukaj czatów' }).fill('ciąg');
  await expect(list.getByRole('listitem')).toHaveCount(1);
  await page.getByRole('searchbox', { name: 'Szukaj czatów' }).fill('');

  await page.getByRole('button', { name: 'Zmień nazwę: Ciągi' }).click();
  await page.getByLabel('Nowa nazwa czatu').fill('Ciągi liczbowe');
  await page.getByLabel('Nowa nazwa czatu').press('Enter');
  await expect(page.getByRole('link', { name: 'Ciągi liczbowe' })).toBeVisible();

  // Escape closes the menu and gives focus back to its button.
  await page.keyboard.press('Escape');
  await expect(list).toBeHidden();
  await expect(menu).toBeFocused();

  await menu.click();
  await page.getByRole('link', { name: 'Ciągi liczbowe' }).click();
  await expect(menu).toHaveAccessibleName('Czat: Ciągi liczbowe');
  await menu.click();
  await page.getByRole('button', { name: 'Usuń czat: Ciągi liczbowe' }).click();
  await page.getByRole('button', { name: 'Tak, usuń' }).click();
  await expect(page).toHaveURL(/\/ai$/);
  await expect(page.getByRole('link', { name: 'Ciągi liczbowe' })).toHaveCount(0);
  await expect(list.getByRole('listitem')).toHaveCount(1);
});

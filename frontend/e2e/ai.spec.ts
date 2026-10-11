import { expect, test } from '@playwright/test';

// The server's fake Chat and the bank are shared by every test; a test that changes them puts them
// back.
test.afterEach(({ request }) => request.post('/api/e2e/reset'));

test('the Teacher asks for Items and sees the job card finish', async ({ page }) => {
  await page.goto('/ai');
  await expect(page.getByRole('heading', { level: 1, name: 'Classlop AI' })).toBeVisible();
  await expect(page.getByText('Nie ma jeszcze czatów.')).toBeVisible();

  // A request that is not clear is answered with a question.
  await page.getByLabel('Wiadomość').fill('Potrzebuję zadań z równań');
  await page.getByRole('button', { name: 'Wyślij' }).click();
  await expect(page).toHaveURL(/\/ai\/[0-9A-Za-z]+$/);
  const log = page.getByRole('log', { name: 'Rozmowa' });
  await expect(log.getByText('Ile zadań, jakiej trudności i w jakim formacie?')).toBeVisible();
  await expect(page.getByRole('link', { name: /Potrzebuję zadań z równań/ })).toBeVisible();

  await page.getByLabel('Wiadomość').fill('Wygeneruj 3 łatwe zadania zamknięte');
  await page.getByRole('button', { name: 'Wyślij' }).click();
  await expect(log.getByText('Zaczynam generować 3 zadania.')).toBeVisible();

  // The card follows the job on the event stream, and the chat list says a job runs.
  const card = log.getByRole('region', { name: 'Generowanie zadań' });
  await expect(card.getByText(/Pisanie zadań \(\d z 3\)/)).toBeVisible();
  await expect(page.getByLabel('Trwające zadania: 1')).toBeVisible();
  await expect(card.getByRole('listitem').filter({ hasText: 'Gotowe' }).first()).toHaveClass(
    'done',
    { timeout: 15_000 },
  );
  const added = card.getByRole('list', { name: 'Dodane zadania' }).getByRole('listitem');
  await expect(added).toHaveCount(3);
  await expect(added.first().getByText('Zadanie 1')).toBeVisible();
  await expect(page.getByLabel('Trwające zadania: 1')).toHaveCount(0);

  // Details open on the card, and retire takes the Item out of the bank.
  await added.first().getByText('Szczegóły').click();
  await expect(added.first().getByText('Rozwiązanie wzorcowe:')).toBeVisible();
  await added.first().getByRole('button', { name: 'Usuń zadanie 1' }).click();
  await expect(added.first().getByText('usunięte')).toBeVisible();

  // Leaving and coming back shows the history and the finished job.
  await page.getByRole('link', { name: 'Bank zadań' }).click();
  await page.getByRole('link', { name: 'Classlop AI', exact: true }).click();
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

  const log = page.getByRole('log', { name: 'Rozmowa' });
  const card = log.getByRole('region', { name: 'Plik zestaw.pdf' });
  const similar = card.getByRole('list', { name: 'Podobne zadania' });
  await expect(similar).toBeVisible({ timeout: 15_000 });
  await expect(
    card.getByRole('list', { name: 'Dodane zadania' }).getByRole('listitem'),
  ).toHaveCount(1);

  await similar.getByRole('button', { name: 'Pomiń' }).click();
  await expect(similar).toHaveCount(0);
});

test('chats are searched, renamed and deleted', async ({ page, request }) => {
  await page.goto('/ai');
  for (const text of ['Nierówności', 'Ciągi']) {
    await page.getByLabel('Wiadomość').fill(text);
    await page.getByRole('button', { name: 'Wyślij' }).click();
    await expect(page.getByRole('link', { name: text })).toBeVisible();
    await page.getByRole('link', { name: '+ Nowy czat' }).click();
    await expect(page.getByText('Napisz, jakich zadań potrzebujesz')).toBeVisible();
  }
  const list = page.getByRole('list', { name: 'Lista czatów' });
  await expect(list.getByRole('listitem')).toHaveCount(2);

  await page.getByRole('searchbox', { name: 'Szukaj czatów' }).fill('ciąg');
  await expect(list.getByRole('listitem')).toHaveCount(1);
  await page.getByRole('searchbox', { name: 'Szukaj czatów' }).fill('');

  await page.getByRole('button', { name: 'Zmień nazwę: Ciągi' }).click();
  await page.getByLabel('Nowa nazwa czatu').fill('Ciągi liczbowe');
  await page.getByLabel('Nowa nazwa czatu').press('Enter');
  await expect(page.getByRole('link', { name: 'Ciągi liczbowe' })).toBeVisible();

  await page.getByRole('link', { name: 'Ciągi liczbowe' }).click();
  await page.getByRole('button', { name: 'Usuń czat: Ciągi liczbowe' }).click();
  await page.getByRole('button', { name: 'Tak' }).click();
  await expect(page.getByRole('link', { name: 'Ciągi liczbowe' })).toHaveCount(0);
  await expect(page).toHaveURL(/\/ai$/);
  await expect(list.getByRole('listitem')).toHaveCount(1);
});

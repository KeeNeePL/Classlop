import { expect, test } from '@playwright/test';

// What the test gives changes the bank's stock; it is put back.
test.afterEach(({ request }) => request.post('/api/e2e/reset'));

test('the Teacher gives an Assignment to the Class', async ({ page, request }) => {
  await page.goto('/klasy/1a');
  await page.getByRole('link', { name: '+ Nowa praca' }).click();
  await expect(page).toHaveURL(/\/klasy\/1a\/nowa-praca$/);
  await expect(page.getByRole('heading', { level: 1, name: /Nowa praca/ })).toBeVisible();

  // Nothing to pick yet, and the page says what is missing.
  const pickButton = page.getByRole('button', { name: 'Dobierz zadania z banku' });
  await expect(pickButton).toBeDisabled();
  await expect(page.getByText('Dodaj dział i wpisz, ile zadań ma z niego być.')).toBeVisible();

  // A section joins the table only when the Teacher clicks Dodaj dział; the list stays ready.
  const section = page.getByLabel('Dział do dodania');
  const add = page.getByRole('button', { name: 'Dodaj dział', exact: true });
  await expect(add).toBeDisabled();
  await section.selectOption({ label: 'III. Równania i nierówności' });
  await expect(page.getByRole('row', { name: /III. Równania/ })).toHaveCount(0);
  await add.click();
  await expect(page.getByLabel('Tytuł')).toHaveValue('III. Równania i nierówności');
  await expect(section.locator('option:checked')).toHaveText('Wybierz dział…');
  await section.selectOption({ label: 'II. Wyrażenia algebraiczne' });
  await add.click();
  await expect(
    page.getByText('Wpisz w tabeli, ile zadań ma być (przynajmniej jedno).'),
  ).toBeVisible();
  await page.getByLabel('Tytuł').fill('Równania kwadratowe');

  // The bank's stock shows per cell, and asking for more is marked.
  const hard = page.getByLabel('trudne, III. Równania i nierówności');
  await expect(hard.locator('xpath=following-sibling::div')).toHaveText('w banku: 1');
  await hard.fill('1');
  await page.getByLabel('łatwe, II. Wyrażenia algebraiczne').fill('2');
  await page.getByRole('button', { name: 'Dobierz zadania z banku' }).click();

  // The preview names what the bank lacks, and the Items it picked.
  const items = page.getByRole('list', { name: 'Zadania w pracy' }).getByRole('listitem');
  await expect(items).toHaveCount(2);
  const note = page.getByRole('status');
  await expect(note).toHaveText(
    'W banku zabrakło: brakuje 1 z 2: II. Wyrażenia algebraiczne, łatwe. Dodaj zadania do banku.',
  );
  await expect(page.getByRole('button', { name: /Wygeneruj/ })).toHaveCount(0);
  await expect(page.getByText('2 zadania · 2 pkt')).toBeVisible();

  // Nothing else in the bank for the cell, so a swap says so; removing empties the preview.
  await items.first().getByRole('button', { name: 'podmień na inne' }).click();
  await expect(page.getByText('Brak innych pasujących zadań w banku.')).toBeVisible();
  await items.last().getByRole('button', { name: 'usuń' }).click();
  await items.last().getByRole('button', { name: 'usuń' }).click();
  await expect(items).toHaveCount(1);
  await expect(page.getByText('Brak zadań.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Opublikuj w Teams' })).toBeDisabled();

  // Back to the form and pick again: the bank still falls short, so the work cannot be given.
  const give = page.getByRole('button', { name: 'Opublikuj w Teams' });
  await page.getByRole('button', { name: '← Wróć do formularza' }).click();
  await page.getByRole('button', { name: 'Dobierz zadania z banku' }).click();
  await expect(items).toHaveCount(2);
  await page.getByLabel('Termin oddania').fill('2099-05-04T18:00');
  await expect(give).toBeDisabled();
  await expect(page.getByText(/^W banku zabrakło zadań\./)).toBeVisible();

  // Asking for no more than the bank has clears the shortfall, and the work can be given.
  await page.getByRole('button', { name: '← Wróć do formularza' }).click();
  await page.getByLabel('łatwe, II. Wyrażenia algebraiczne').fill('1');
  await page.getByRole('button', { name: 'Dobierz zadania z banku' }).click();
  await expect(items).toHaveCount(2);
  await expect(note).toHaveCount(0);
  await give.click();

  await expect(page.getByText('Praca «Równania kwadratowe» wydana w Teams.')).toBeVisible();
  expect(await (await request.post('/api/e2e/posts')).json()).toContain('Równania kwadratowe.pdf');
});

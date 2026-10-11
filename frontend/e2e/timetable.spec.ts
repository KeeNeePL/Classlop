import { expect, test } from '@playwright/test';

// The tenant is FakeTeams, shared by every test on the server; a test that changes it puts it back.
test.afterEach(({ request }) => request.post('/api/e2e/reset'));

/** The Warsaw day `days` from today, as a `date` input's YYYY-MM-DD. */
const day = (days: number) =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Warsaw' }).format(
    new Date(Date.now() + days * 86_400_000),
  );

test('the Teacher enters a Timetable with an added slot, then a break', async ({ page }) => {
  await page.goto('/klasy/nowa');
  await page.getByRole('button', { name: 'Połącz zespół: Klasa 2A matematyka' }).click();
  await page.getByRole('link', { name: 'Ustawienia klasy' }).click();

  await page.getByRole('button', { name: '+ Dodaj slot' }).click();
  await page.getByLabel('Dzień slotu 2').selectOption('czwartek');
  await page.getByLabel('Początek slotu 2').fill('10:00');
  await page.getByLabel('Koniec slotu 2').fill('10:45');
  // Four weeks, today's included: four Lessons of each slot.
  await page.getByLabel('Koniec roku szkolnego').fill(day(27));
  await page.getByRole('button', { name: 'Zapisz plan lekcji' }).click();

  const slots = page.getByRole('list', { name: 'Sloty planu' });
  await expect(slots.getByRole('listitem')).toHaveText([
    'poniedziałek 08:00–08:45',
    'czwartek 10:00–10:45',
  ]);

  // The Lessons the break will cancel show before it is confirmed: one of each slot.
  await page.getByLabel('Przerwa od').fill(day(7));
  await page.getByLabel('Przerwa do').fill(day(13));
  const affected = page.getByRole('list', { name: 'Lekcje do odwołania' });
  await expect(affected.getByRole('listitem')).toHaveCount(2);
  await page.getByRole('button', { name: 'Odwołaj lekcje' }).click();
  await expect(page.getByLabel('Przerwa od')).toHaveValue('');

  // Cancelled in Teams, so a break of the same dates has nothing left to cancel.
  await page.getByLabel('Przerwa od').fill(day(7));
  await page.getByLabel('Przerwa do').fill(day(13));
  await expect(affected).toHaveText('W tych dniach nie ma lekcji.');
  await expect(page.getByRole('button', { name: 'Odwołaj lekcje' })).toBeDisabled();

  // A slot changed from a date shows the old slot's Lessons it replaces: two Mondays.
  await page.getByLabel('Slot do zmiany').selectOption('poniedziałek 08:00–08:45');
  await page.getByLabel('Nowy dzień').selectOption('wtorek');
  await page.getByLabel('Zmiana od').fill(day(14));
  await expect(
    page.getByRole('list', { name: 'Lekcje do zastąpienia' }).getByRole('listitem'),
  ).toHaveCount(2);
  await expect(page.getByRole('status')).toContainText(
    'Lekcje nowego slotu do końca roku szkolnego: 2',
  );
  await page.getByRole('button', { name: 'Zmień slot' }).click();
  await expect(slots.getByRole('listitem')).toHaveText([
    'wtorek 08:00–08:45',
    'czwartek 10:00–10:45',
  ]);
});

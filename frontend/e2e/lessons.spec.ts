import { expect, test } from '@playwright/test';

// The tenant is FakeTeams, shared by every test on the server; a test that changes it puts it back.
test.afterEach(({ request }) => request.post('/api/e2e/reset'));

const day = (offset: number) =>
  new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);

/** Links the demo tenant's first team as a Class and returns its id. */
async function linkedClass(request: import('@playwright/test').APIRequestContext) {
  const [team] = await (await request.get('/api/teams')).json();
  return (await (await request.post('/api/classes/link', { data: { team_id: team.id } })).json())
    .id as string;
}

test("the Teacher adds a Lesson and overrides one Student's Attendance", async ({
  page,
  request,
}) => {
  const id = await linkedClass(request);
  await page.goto(`/klasy/${id}/lekcje`);

  // A single Lesson needs its Lesson topic.
  await page.getByLabel('Początek').fill(`${day(-1)}T08:00`);
  await page.getByLabel('Koniec').fill(`${day(-1)}T08:45`);
  const add = page.getByRole('button', { name: 'Dodaj lekcję' });
  await expect(add).toBeDisabled();
  await page.getByLabel('Temat lekcji').fill('Funkcje liniowe');
  await add.click();
  const list = page.getByRole('list', { name: 'Lekcje' });
  await expect(list).toContainText('Funkcje liniowe');

  await request.post(`/api/e2e/attend?class_id=${id}`);
  await list.getByRole('link', { name: 'Funkcje liniowe' }).click();
  await expect(page.getByText('Frekwencja jeszcze nie została pobrana')).toBeVisible();
  await page.getByRole('button', { name: 'Odśwież frekwencję' }).click();

  const jan = page.getByLabel('Frekwencja: Jan Kowalski');
  const ewa = page.getByLabel('Frekwencja: Ewa Zielinska');
  const piotr = page.getByLabel('Frekwencja: Piotr Wisniewski');
  await expect(jan.locator('option:checked')).toHaveText('Obecny');
  await expect(ewa.locator('option:checked')).toHaveText('Spóźniony');
  await expect(piotr.locator('option:checked')).toHaveText('Nieobecny');

  // An override is marked and survives a refresh.
  await piotr.selectOption({ label: 'Obecny' });
  const row = page.getByRole('row', { name: /Piotr Wisniewski/ });
  await expect(row).toContainText('zmienione');
  await page.getByRole('button', { name: 'Odśwież frekwencję' }).click();
  await page.reload();
  await expect(piotr.locator('option:checked')).toHaveText('Obecny');
  await expect(row).toContainText('zmienione');
  await expect(page.getByRole('row', { name: /Jan Kowalski/ })).not.toContainText('zmienione');

  // Piotrek W. was in the call without being a Student: linking him is remembered.
  await page.getByLabel('Uczeń dla: Piotrek W.').selectOption({ label: 'Piotr Wisniewski' });
  await page.getByRole('button', { name: 'Połącz: Piotrek W.' }).click();
  await expect(page.getByRole('list', { name: 'Niepołączeni uczestnicy' })).toHaveCount(0);
});

test('a Teams meeting that needs sorting is asked about on Do zrobienia and placed by the answer', async ({
  page,
  request,
}) => {
  const id = await linkedClass(request);
  await request.post(`/api/e2e/meeting?class_id=${id}`);

  // Opening the tab brings the Teacher's Teams calendar in.
  await page.goto(`/klasy/${id}/lekcje`);
  await expect(page.getByRole('list', { name: 'Lekcje' })).toBeVisible();
  await page.goto('/');
  const ask = page.getByRole('group', { name: 'Do której klasy należy to spotkanie?' });
  await expect(page.getByText('Wycieczka do muzeum')).toBeVisible();
  await ask.getByRole('button', { name: 'Klasa 2A matematyka' }).click();

  await expect(page.getByText('Wycieczka do muzeum')).toHaveCount(0);
  await page.goto(`/klasy/${id}/lekcje`);
  await expect(page.getByRole('list', { name: 'Lekcje' }).getByRole('listitem')).toHaveCount(1);
});

test('the lateness threshold is one setting on Ustawienia', async ({ page }) => {
  await page.goto('/ustawienia');
  const minutes = page.getByLabel('Próg spóźnienia w minutach');
  await expect(minutes).toHaveValue('5');

  await minutes.fill('10');
  await page.getByRole('button', { name: 'Zapisz próg spóźnienia' }).click();
  await expect(page.getByRole('status')).toHaveText('Zapisano.');

  await page.reload();
  await expect(minutes).toHaveValue('10');
});

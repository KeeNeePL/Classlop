import { Component, computed, inject, resource, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { Api } from '../api/api';
import { overviewApiClassesClassIdOverviewGet } from '../api/functions';
import { AssignmentRow } from '../api/models';
import { warsaw } from '../time';
import { Badge } from '../ui/badge';
import { Hint } from '../ui/hint';
import { Invented } from '../ui/invented';
import { LineChart } from '../ui/line-chart';
import { MathText } from '../ui/math';
import { Panel } from '../ui/panel';
import { ProgressBar } from '../ui/progress-bar';

const TYPE: Record<AssignmentRow['type'], string> = {
  homework: 'Praca domowa',
  quiz: 'Kartkówka',
  exam: 'Sprawdzian',
};
const STATE: Record<AssignmentRow['state'], string> = {
  draft: 'Szkic',
  scheduled: 'Zaplanowana',
  open: 'Zbieranie prac',
  closed: 'Zamknięta',
};

const HINTS = {
  progress:
    'Punkty zdobyte podzielone przez punkty do zdobycia, z zadań już ocenionych. ' +
    'Zadanie przypisane do kilku tematów liczy się w całości w każdym z nich, a w dziale raz. ' +
    'Nie liczą się prace nieoddane, zwolnione ani wstrzymane do sprawdzenia. ' +
    '„brak danych” znaczy, że nic z tego nie zostało jeszcze ocenione.',
  assignments:
    'Wykres: średni wynik klasy w każdej pracy, w dniu jej terminu. To wszystkie zdobyte ' +
    'punkty podzielone przez wszystkie możliwe, z prac ocenionych. Przerwa w linii znaczy, ' +
    'że praca nie ma jeszcze ocenionych wyników. Kolumna „Średnia” w tabeli to ta sama liczba.',
  attention:
    'Uczeń trafia tu, gdy nie oddał 2 z ostatnich 5 prac, ma wynik poniżej 30% albo 3 ' +
    'nieobecności w ostatnich 10 lekcjach. Lista pokazuje najwyżej pięć osób, od tych, ' +
    'którym trzeba poświęcić najwięcej uwagi.',
  students:
    'Wynik ucznia: punkty zdobyte podzielone przez punkty do zdobycia ze wszystkich jego ' +
    'ocenionych prac. Prace nieoddane, zwolnione i wstrzymane do sprawdzenia się nie liczą.',
};

/** The Class page's Przegląd tab. */
@Component({
  imports: [Badge, Hint, Invented, LineChart, MathText, Panel, ProgressBar, RouterLink],
  templateUrl: './class-overview.html',
  styleUrl: './class-overview.css',
})
export class ClassOverview {
  private readonly api = inject(Api);
  private readonly id = toSignal(
    inject(ActivatedRoute).paramMap.pipe(map((p) => p.get('klasa') ?? '')),
    { requireSync: true },
  );

  protected readonly overview = resource({
    params: () => this.id(),
    loader: ({ params }) =>
      this.api.invoke(overviewApiClassesClassIdOverviewGet, { class_id: params }),
  }).value;

  protected readonly hints = HINTS;
  protected readonly tab = signal<'sections' | 'topics'>('sections');
  protected readonly line = computed(
    () =>
      this.overview()?.average_line.map((p) => ({ at: p.due, percent: p.percent ?? null })) ?? [],
  );

  protected readonly type = (a: AssignmentRow) => TYPE[a.type];
  protected readonly state = (a: AssignmentRow) => STATE[a.state];
  protected readonly due = (a: AssignmentRow) => warsaw(a.due);
  protected readonly link = (student: string) => ['/klasy', this.id(), 'uczniowie', student];
}

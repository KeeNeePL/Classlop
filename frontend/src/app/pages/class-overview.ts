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
import { Percent } from '../ui/percent';

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

const KIND: Record<AssignmentRow['type'], string> = {
  quiz: 'Kartkówki',
  exam: 'Sprawdziany',
  homework: 'Prace domowe',
};

const HINTS = {
  progress:
    'Procent punktów zdobytych z możliwych do zdobycia w ocenionych zadaniach, osobno dla ' +
    'kartkówek, sprawdzianów i prac domowych. „Średnia” to wynik całej kategorii. Zadanie ' +
    'przypisane do kilku tematów liczy się w całości w każdym z nich, a w dziale raz. Nie ' +
    'liczą się prace nieoddane, zwolnione ani wstrzymane do sprawdzenia. „brak danych” znaczy, ' +
    'że nic z tego nie zostało jeszcze ocenione.',
  assignments:
    'Wykres: średni wynik klasy w każdej pracy, w dniu jej terminu. To wszystkie zdobyte ' +
    'punkty podzielone przez wszystkie możliwe, z prac ocenionych. Przerwa w linii znaczy, ' +
    'że praca nie ma jeszcze ocenionych wyników. Kolumna „Średnia” w tabeli to ta sama liczba.',
  attention:
    'Uczeń trafia tu, gdy nie oddał 2 z ostatnich 5 prac, ma wynik poniżej 30% albo 3 ' +
    'nieobecności w ostatnich 10 lekcjach. Lista pokazuje najwyżej pięć osób, od tych, ' +
    'którym trzeba poświęcić najwięcej uwagi.',
  students:
    'Średni wynik ucznia ze wszystkich kategorii razem (kartkówki, sprawdziany, prace ' +
    'domowe): procent punktów zdobytych z możliwych w jego ocenionych zadaniach. Prace ' +
    'nieoddane, zwolnione i wstrzymane do sprawdzenia się nie liczą.',
};

/** The Class page's Przegląd tab. */
@Component({
  imports: [Badge, Hint, Invented, LineChart, MathText, Panel, Percent, RouterLink],
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
  protected readonly kind = KIND;
  protected readonly tab = signal<'sections' | 'topics'>('sections');
  protected readonly line = computed(
    () =>
      this.overview()?.average_line.map((p) => ({ at: p.due, percent: p.percent ?? null })) ?? [],
  );

  /** One row per Curriculum section, with a cell for each Assignment type, in the same order. */
  protected readonly rows = computed(() => {
    const columns = this.overview()?.progress ?? [];
    return (columns[0]?.sections ?? []).map((section, i) => ({
      id: section.id,
      name: section.name,
      cells: columns.map((c) => c.sections[i]),
      topics: section.topics.map((topic, j) => ({
        id: topic.id,
        name: topic.name,
        cells: columns.map((c) => c.sections[i].topics[j]),
      })),
    }));
  });

  protected readonly type = (a: AssignmentRow) => TYPE[a.type];
  protected readonly state = (a: AssignmentRow) => STATE[a.state];
  protected readonly due = (a: AssignmentRow) => warsaw(a.due);
  protected readonly link = (student: string) => ['/klasy', this.id(), 'uczniowie', student];
}

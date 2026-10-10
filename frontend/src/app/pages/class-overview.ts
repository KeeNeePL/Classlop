import { Component, computed, inject, resource, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { Api } from '../api/api';
import { overviewApiClassesClassIdOverviewGet } from '../api/functions';
import { AssignmentRow } from '../api/models';
import { AssignmentLanes } from './assignment-lanes';
import { Badge } from '../ui/badge';
import { Hint } from '../ui/hint';
import { Invented } from '../ui/invented';
import { MathText } from '../ui/math';
import { Panel } from '../ui/panel';
import { Percent } from '../ui/percent';

const RECENT = 4;

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
    'że nic z tego nie zostało jeszcze ocenione. Na start widać 4 działy, z których ostatnio ' +
    'oceniono prace; „Rozwiń” pokazuje wszystkie.',
  assignments:
    'Kiedy zadano każdą pracę: oś pozioma to czas. Ikonka to typ pracy (kartka z ptaszkiem: ' +
    'sprawdzian, długopis: kartkówka, domek: praca domowa), jej kolor to stan (legenda pod ' +
    'wykresem). Czerwona linia to dziś. Najedź na ikonkę, żeby zobaczyć termin, liczbę ' +
    'oddanych prac i średni wynik klasy.',
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
  imports: [AssignmentLanes, Badge, Hint, Invented, MathText, Panel, Percent, RouterLink],
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

  protected readonly expanded = signal(false);

  /** One row per Curriculum section, with a cell for each Assignment type, in the same order.
   * Folded, only the RECENT sections most recently assessed, newest first. */
  protected readonly rows = computed(() => {
    const o = this.overview();
    const columns = o?.progress ?? [];
    const rows = (columns[0]?.sections ?? []).map((section, i) => ({
      id: section.id,
      name: section.name,
      cells: columns.map((c) => c.sections[i]),
      topics: section.topics.map((topic, j) => ({
        id: topic.id,
        name: topic.name,
        cells: columns.map((c) => c.sections[i].topics[j]),
      })),
    }));
    if (this.expanded()) return rows;
    const recent = (o?.recent_sections ?? []).slice(0, RECENT);
    return recent.flatMap((id) => rows.filter((r) => r.id === id));
  });

  protected readonly link = (student: string) => ['/klasy', this.id(), 'uczniowie', student];
}

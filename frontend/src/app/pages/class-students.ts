import { Component, computed, inject, resource } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { Api } from '../api/api';
import { overviewApiClassesClassIdOverviewGet } from '../api/functions';
import { StudentRow } from '../api/models';
import { Badge } from '../ui/badge';
import { Hint } from '../ui/hint';
import { Invented } from '../ui/invented';
import { Panel } from '../ui/panel';
import { Percent } from '../ui/percent';

const HINTS = {
  invented:
    'Prawdziwe: zadania z banku z ich tematami i punktami oraz punkty uczniów. Na razie ' +
    'zmyślone: uczniowie, ich prace i nieobecności.',
  percent:
    'Średni wynik ucznia ze wszystkich kategorii razem (kartkówki, sprawdziany, prace ' +
    'domowe): procent punktów zdobytych z możliwych w jego ocenionych zadaniach. Prace ' +
    'nieoddane, zwolnione i wstrzymane do sprawdzenia się nie liczą.',
  handed:
    'Ile prac uczeń oddał ze wszystkich, które dostał, łącznie z tymi, których termin ' +
    'jeszcze nie minął. Zwolnienia się nie liczą.',
  absent: 'Nieobecności na wszystkich lekcjach tej klasy.',
  attention:
    'Te same powody co w „Wymagają uwagi” na przeglądzie: 2 nieoddane z ostatnich 5 prac, ' +
    'wynik poniżej 30% albo 3 nieobecności w ostatnich 10 lekcjach.',
};

const COLUMNS = {
  uczen: (s: StudentRow) => s.name,
  wynik: (s: StudentRow) => s.percent ?? -1,
  oddane: (s: StudentRow) => (s.given ? s.handed_in / s.given : 1),
  nieobecnosci: (s: StudentRow) => s.absent,
};
type Column = keyof typeof COLUMNS;

/** The Class page's Uczniowie tab: every Student with their figures, searchable and sortable;
 * the search and the sort live in the URL, so coming back from a Student report keeps them. */
@Component({
  imports: [Badge, Hint, Invented, Panel, Percent, RouterLink],
  templateUrl: './class-students.html',
  styleUrl: './class-students.css',
})
export class ClassStudents {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly id = toSignal(this.route.paramMap.pipe(map((p) => p.get('klasa') ?? '')), {
    requireSync: true,
  });
  private readonly query = toSignal(this.route.queryParamMap, { requireSync: true });

  protected readonly overview = resource({
    params: () => this.id(),
    loader: ({ params }) =>
      this.api.invoke(overviewApiClassesClassIdOverviewGet, { class_id: params }),
  }).value;

  protected readonly hints = HINTS;
  protected readonly search = computed(() => this.query().get('szukaj') ?? '');
  protected readonly sort = computed(() => {
    const raw = this.query().get('sort') ?? 'uczen';
    const column = raw.replace(/^-/, '');
    return {
      column: (column in COLUMNS ? column : 'uczen') as Column,
      down: raw.startsWith('-'),
    };
  });

  protected readonly rows = computed(() => {
    const needle = this.search().trim().toLocaleLowerCase('pl');
    const { column, down } = this.sort();
    const key = COLUMNS[column];
    const byName = (a: StudentRow, b: StudentRow) => a.name.localeCompare(b.name, 'pl');
    return (this.overview()?.students ?? [])
      .filter((s) => s.name.toLocaleLowerCase('pl').includes(needle))
      .sort((a, b) => {
        const [x, y] = [key(a), key(b)];
        const order =
          typeof x === 'string' ? x.localeCompare(y as string, 'pl') : x - (y as number);
        return (down ? -order : order) || byName(a, b);
      });
  });

  /** For aria-sort on the column's header. */
  protected readonly sorted = (column: Column) =>
    this.sort().column === column ? (this.sort().down ? 'descending' : 'ascending') : 'none';

  protected readonly arrow = (column: Column) =>
    this.sort().column === column ? (this.sort().down ? '▼' : '▲') : '';

  protected sortBy(column: Column): void {
    const { column: now, down } = this.sort();
    // A new column starts from its most useful end: names A to Z, numbers highest first.
    const nextDown = now === column ? !down : column !== 'uczen';
    this.set({ sort: `${nextDown ? '-' : ''}${column}` });
  }

  protected type(text: string): void {
    this.set({ szukaj: text || null });
  }

  private set(params: Record<string, string | null>): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: params,
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  protected readonly link = (student: string) => ['/klasy', this.id(), 'uczniowie', student];
}

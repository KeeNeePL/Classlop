import { Component, computed, effect, inject, resource, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { Api } from '../api/api';
import {
  reportApiClassesClassIdStudentsStudentIdReportGet,
  saveNoteApiClassesClassIdStudentsStudentIdNotePut,
} from '../api/functions';
import { ReportRow } from '../api/models';
import { fromInput, shortDate, warsaw } from '../time';
import { Badge } from '../ui/badge';
import { Hint } from '../ui/hint';
import { Invented } from '../ui/invented';
import { LineChart } from '../ui/line-chart';
import { Panel } from '../ui/panel';
import { Percent } from '../ui/percent';

type Type = ReportRow['type'];
type Period = 'all' | 'school-year' | 'last-30' | 'custom';

const KIND: Record<Type, string> = {
  quiz: 'Kartkówka',
  exam: 'Sprawdzian',
  homework: 'Praca domowa',
};
const COLUMNS: Record<Type, string> = {
  quiz: 'Kartkówki',
  exam: 'Sprawdziany',
  homework: 'Prace domowe',
};
const STATE: Record<ReportRow['submission_state'], string> = {
  not_handed_in: 'nie oddano',
  handed_in: 'oddano, ocenia AI',
  graded: 'ocenione',
  returned: 'zwrócone',
  missing: 'brak pracy',
  excused: 'zwolniony',
};
const DAY = 86_400_000;

const HINTS = {
  period:
    'Okres liczy się po terminie oddania prac i po dacie lekcji. „Od 1 września” to obecny rok ' +
    'szkolny.',
  progress:
    'Procent punktów ucznia w ocenionych zadaniach, osobno dla kartkówek, sprawdzianów i prac ' +
    'domowych, jak w przeglądzie klasy. Nie liczą się prace nieoddane, zwolnione ani czekające ' +
    'na sprawdzenie.',
  chart:
    'Jeden punkt na każdą pracę, w terminie jej oddania. Brak pracy i zwolnienie zostawiają ' +
    'lukę, nie 0. Przerywana linia to średnia klasy z tej pracy, liczona tylko wśród uczniów, ' +
    'którzy ją dostali.',
  note: 'Prywatna notatka; widzisz ją tylko ty i nie trafia do żadnego eksportu.',
};

/** September 1 of the school year `now` is in. */
const schoolYear = (now: Date) => {
  const year = now.getMonth() >= 8 ? now.getFullYear() : now.getFullYear() - 1;
  return fromInput(`${year}-09-01T00:00`);
};

/** One Student over a chosen period: Attendance, counts, Progress, their Assignments with the
 * Suggested grade, a line against the Class average, and the Teacher's private Note. */
@Component({
  imports: [Badge, FormsModule, Hint, Invented, LineChart, Panel, Percent, RouterLink],
  templateUrl: './student-report.html',
  styleUrl: './student-report.css',
})
export class StudentReport {
  private readonly api = inject(Api);
  private readonly params = toSignal(
    inject(ActivatedRoute).paramMap.pipe(
      map((p) => ({ klasa: p.get('klasa') ?? '', uczen: p.get('uczen') ?? '' })),
    ),
    { requireSync: true },
  );

  protected readonly period = signal<Period>('all');
  protected readonly from = signal('');
  protected readonly to = signal('');
  protected readonly type = signal<Type | null>(null);

  /** The period as ISO 8601 UTC bounds, or none. */
  private readonly bounds = computed(() => {
    const now = new Date();
    switch (this.period()) {
      case 'school-year':
        return { start: schoolYear(now) };
      case 'last-30':
        return { start: new Date(now.getTime() - 30 * DAY).toISOString() };
      case 'custom':
        return {
          start: this.from() ? fromInput(`${this.from()}T00:00`) : undefined,
          end: this.to() ? fromInput(`${this.to()}T23:59`) : undefined,
        };
      default:
        return {};
    }
  });

  private readonly page = resource({
    params: () => ({ ...this.params(), ...this.bounds() }),
    loader: ({ params }) =>
      this.api.invoke(reportApiClassesClassIdStudentsStudentIdReportGet, {
        class_id: params.klasa,
        student_id: params.uczen,
        start: params.start,
        end: params.end,
      }),
  });
  // The value of a resource in its error state throws, so a 404 reads as no view.
  protected readonly view = computed(() => (this.page.hasValue() ? this.page.value() : undefined));
  protected readonly missing = computed(() => this.page.error() !== undefined);

  protected readonly kind = KIND;
  protected readonly columns = COLUMNS;
  protected readonly types = Object.keys(KIND) as Type[];
  protected readonly hints = HINTS;
  protected readonly warsaw = warsaw;
  protected readonly back = computed(() => ['/klasy', this.params().klasa]);
  protected readonly state = (r: ReportRow) =>
    r.held ? 'czeka na sprawdzenie' : STATE[r.submission_state];

  protected readonly rows = computed(() => {
    const t = this.type();
    return (this.view()?.assignments ?? []).filter((a) => !t || a.type === t);
  });

  private readonly shown = computed(() => {
    const t = this.type();
    return (this.view()?.points ?? []).filter((p) => !t || p.type === t);
  });
  protected readonly labels = computed(() =>
    this.shown().map((p) => `${shortDate(p.due)} ${p.title}`),
  );
  protected readonly lines = computed(() => [
    { name: this.view()?.name ?? 'Uczeń', values: this.shown().map((p) => p.percent) },
    { name: 'Średnia klasy', values: this.shown().map((p) => p.class_average), dashed: true },
  ]);

  /** Progress rows: the four sections with the newest graded work, one cell per type. */
  protected readonly progress = computed(() => {
    const v = this.view();
    if (!v) return [];
    const columns = v.progress;
    return v.recent_sections.slice(0, 4).map((id) => {
      const at = columns[0].sections.findIndex((s) => s.id === id);
      return {
        id,
        name: columns[0].sections[at].name,
        cells: columns.map((c) => c.sections[at].percent),
      };
    });
  });

  protected readonly note = signal('');
  protected readonly saved = signal<'idle' | 'dirty' | 'saving' | 'saved' | 'failed'>('idle');

  constructor() {
    effect(() => {
      this.params();
      this.saved.set('idle');
    });
    // The Note in the box follows the Student shown until the Teacher types.
    effect(() => {
      const v = this.view();
      if (v && this.saved() === 'idle') this.note.set(v.note);
    });
  }

  protected async saveNote() {
    this.saved.set('saving');
    try {
      await this.api.invoke(saveNoteApiClassesClassIdStudentsStudentIdNotePut, {
        class_id: this.params().klasa,
        student_id: this.params().uczen,
        body: { text: this.note() },
      });
      this.saved.set('saved');
    } catch {
      this.saved.set('failed');
    }
  }
}

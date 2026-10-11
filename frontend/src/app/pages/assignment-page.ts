import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, resource, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { Api } from '../api/api';
import {
  addRecipientsApiAssignmentsAssignmentIdRecipientsPost,
  assignmentApiClassesClassIdAssignmentsAssignmentIdGet,
  changeTimesApiAssignmentsAssignmentIdTimesPost,
  deleteAssignmentApiAssignmentsAssignmentIdDelete,
} from '../api/functions';
import { AssignmentPage as Page, SummaryRow } from '../api/models';
import { fromInput, shortDate, toInput, warsaw } from '../time';
import { Badge } from '../ui/badge';
import { Hint } from '../ui/hint';
import { Invented } from '../ui/invented';
import { Panel } from '../ui/panel';
import { Percent } from '../ui/percent';

const KIND: Record<Page['type'], string> = {
  quiz: 'Kartkówka',
  exam: 'Sprawdzian',
  homework: 'Praca domowa',
};

const STATE: Record<SummaryRow['state'], string> = {
  not_handed_in: 'nie oddano',
  handed_in: 'oddano, ocenia AI',
  graded: 'ocenione',
  returned: 'zwrócone',
  missing: 'brak pracy',
  excused: 'zwolniony',
};

const HINTS = {
  summary:
    'Do terminu oddania widać tylko, ile prac oddano. Od terminu: średni wynik klasy i rozkład ' +
    'wyników uczniów w przedziałach co 10 punktów procentowych; kreski z liczbą to progi ' +
    'proponowanych ocen. Prace czekające na sprawdzenie, nieoddane i zwolnione się nie liczą.',
  items:
    'Średni procent punktów w każdym zadaniu i najczęstsze błędy, które AI znalazło w co ' +
    'najmniej trzech pracach (najwyżej trzy na zadanie).',
  students:
    'Na górze prace do sprawdzenia: te, przy których AI nie jest pewne odczytu lub oceny ' +
    '(czekają na sprawdzenie i nie wróciły jeszcze do ucznia), i te z rysunkiem. Proponowana ' +
    'ocena wynika z progów w Ustawieniach; widzisz ją tylko ty.',
};

type Form = 'times' | 'add' | 'delete';

/** An AI-graded Assignment: the Assignment summary on top, every recipient's Submission below,
 * and the changes the Teacher can still make to it. */
@Component({
  imports: [Badge, FormsModule, Hint, Invented, Panel, Percent, RouterLink],
  templateUrl: './assignment-page.html',
  styleUrl: './assignment-page.css',
})
export class AssignmentPage {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly params = toSignal(
    inject(ActivatedRoute).paramMap.pipe(
      map((p) => ({ klasa: p.get('klasa') ?? '', praca: p.get('praca') ?? '' })),
    ),
    { requireSync: true },
  );

  private readonly page = resource({
    params: () => this.params(),
    loader: ({ params }) =>
      this.api.invoke(assignmentApiClassesClassIdAssignmentsAssignmentIdGet, {
        class_id: params.klasa,
        assignment_id: params.praca,
      }),
  });
  // The value of a resource in its error state throws, so a 404 reads as no view.
  protected readonly view = computed(() => (this.page.hasValue() ? this.page.value() : undefined));
  protected readonly missing = computed(() => this.page.error() !== undefined);

  protected readonly kind = KIND;
  protected readonly hints = HINTS;
  protected readonly warsaw = warsaw;
  protected readonly shortDate = shortDate;

  protected readonly back = computed(() => ['/klasy', this.params().klasa]);
  protected readonly csv = computed(
    () => `/api/classes/${this.params().klasa}/assignments/${this.params().praca}/csv`,
  );
  protected readonly link = (student: string) => [
    '/klasy',
    this.params().klasa,
    'prace',
    this.params().praca,
    student,
  ];

  protected readonly state = (r: SummaryRow) => (r.held ? 'czeka na sprawdzenie' : STATE[r.state]);
  protected readonly tone = (r: SummaryRow) =>
    r.held ? 'warn' : r.state === 'missing' ? 'danger' : r.percent != null ? 'ok' : '';

  /** The 10 bins, each as tall as its share of the fullest one. */
  protected readonly bins = computed(() => {
    const counts = this.view()?.histogram ?? [];
    const top = Math.max(1, ...counts);
    return counts.map((count, i) => ({
      count,
      label: i === counts.length - 1 ? `${10 * i}–100` : `${10 * i}–${10 * i + 9}`,
      height: (100 * count) / top,
    }));
  });
  /** Grade n + 2 starts at thresholds[n]. */
  protected readonly marks = computed(() =>
    (this.view()?.thresholds ?? []).map((at, n) => ({ at, grade: n + 2 })),
  );

  protected readonly form = signal<Form | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly due = signal('');
  protected readonly close = signal('');
  protected readonly chosen = signal<ReadonlySet<string>>(new Set());

  protected open(form: Form) {
    const v = this.view();
    if (!v) return;
    this.error.set(null);
    this.due.set(toInput(v.due));
    this.close.set(toInput(v.close));
    this.chosen.set(new Set());
    this.form.set(this.form() === form ? null : form);
  }

  protected toggle(id: string) {
    const next = new Set(this.chosen());
    if (!next.delete(id)) next.add(id);
    this.chosen.set(next);
  }

  protected saveTimes() {
    return this.run(() =>
      this.api.invoke(changeTimesApiAssignmentsAssignmentIdTimesPost, {
        assignment_id: this.params().praca,
        body: { due_at: fromInput(this.due()), close_at: fromInput(this.close()) },
      }),
    );
  }

  protected addStudents() {
    return this.run(() =>
      this.api.invoke(addRecipientsApiAssignmentsAssignmentIdRecipientsPost, {
        assignment_id: this.params().praca,
        body: { student_ids: [...this.chosen()] },
      }),
    );
  }

  protected async remove() {
    const deleted = await this.run(
      () =>
        this.api.invoke(deleteAssignmentApiAssignmentsAssignmentIdDelete, {
          assignment_id: this.params().praca,
        }),
      false,
    );
    if (deleted) await this.router.navigate(this.back());
  }

  /** One change through `teams`; afterwards the page shows the Assignment as it now is. */
  private async run(change: () => Promise<unknown>, reload = true): Promise<boolean> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await change();
      this.form.set(null);
      if (reload) this.page.reload();
      return true;
    } catch (e) {
      this.error.set(
        e instanceof HttpErrorResponse && e.status === 409
          ? 'Teams nie pozwala już na tę zmianę. Odśwież stronę i sprawdź stan pracy.'
          : 'Nie udało się zapisać zmiany. Spróbuj jeszcze raz.',
      );
      return false;
    } finally {
      this.busy.set(false);
    }
  }
}

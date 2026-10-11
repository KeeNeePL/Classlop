import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, resource, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { Api } from '../api/api';
import {
  approveApiSubmissionsSubmissionIdApprovePost,
  editFeedbackApiSubmissionsSubmissionIdItemsItemIdFeedbackPost,
  fixTranscriptionApiSubmissionsSubmissionIdItemsItemIdTranscriptionPost,
  gradeAgainApiSubmissionsSubmissionIdGradeAgainPost,
  overrideApiSubmissionsSubmissionIdItemsItemIdOverridePost,
  submissionApiClassesClassIdAssignmentsAssignmentIdSubmissionsStudentIdGet,
} from '../api/functions';
import { ItemView } from '../api/models';
import { warsaw } from '../time';
import { Badge } from '../ui/badge';
import { Invented } from '../ui/invented';
import { MathText } from '../ui/math';
import { Panel } from '../ui/panel';

const READING: Record<ItemView['reading'], string | null> = {
  readable: null,
  unsure: 'niepewny odczyt',
  unreadable: 'nieczytelne',
  blank: 'puste',
};

type Editing = { item: string; field: 'transcription' | 'feedback' };

/** One Submission Item by Item: the Item, the AI's Transcription, its points and Feedback, and
 * the Teacher's changes, which `grading` carries out. */
@Component({
  imports: [Badge, FormsModule, Invented, MathText, Panel, RouterLink],
  templateUrl: './submission-page.html',
  styleUrl: './submission-page.css',
})
export class SubmissionPage {
  private readonly api = inject(Api);
  private readonly params = toSignal(
    inject(ActivatedRoute).paramMap.pipe(
      map((p) => ({
        klasa: p.get('klasa') ?? '',
        praca: p.get('praca') ?? '',
        uczen: p.get('uczen') ?? '',
      })),
    ),
    { requireSync: true },
  );

  private readonly page = resource({
    params: () => this.params(),
    loader: ({ params }) =>
      this.api.invoke(submissionApiClassesClassIdAssignmentsAssignmentIdSubmissionsStudentIdGet, {
        class_id: params.klasa,
        assignment_id: params.praca,
        student_id: params.uczen,
      }),
  });
  // The value of a resource in its error state throws, so a 404 reads as no view.
  protected readonly view = computed(() => (this.page.hasValue() ? this.page.value() : undefined));
  protected readonly missing = computed(() => this.page.error() !== undefined);

  protected readonly reading = READING;
  protected readonly warsaw = warsaw;
  protected readonly back = computed(() => [
    '/klasy',
    this.params().klasa,
    'prace',
    this.params().praca,
  ]);
  protected readonly link = (student: string) => [...this.back(), student];

  protected readonly editing = signal<Editing | null>(null);
  protected readonly draft = signal('');
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly isEditing = (i: ItemView, field: Editing['field']) =>
    this.editing()?.item === i.item_id && this.editing()?.field === field;

  protected edit(i: ItemView, field: Editing['field']) {
    this.error.set(null);
    this.draft.set(field === 'transcription' ? i.transcription : i.feedback);
    this.editing.set({ item: i.item_id, field });
  }

  protected setPoints(i: ItemView, value: string) {
    const points = Number(value);
    if (value === '' || points === i.points) return;
    return this.run(
      () =>
        this.api.invoke(overrideApiSubmissionsSubmissionIdItemsItemIdOverridePost, {
          ...this.ids(i),
          body: { handed_in_at: this.handedIn(), points },
        }),
      `Punkty za zadanie ${i.number} muszą być od 0 do ${i.max_points}.`,
    );
  }

  protected save(i: ItemView) {
    const field = this.editing()?.field;
    const body = { handed_in_at: this.handedIn() };
    return this.run(
      () =>
        field === 'transcription'
          ? this.api.invoke(
              fixTranscriptionApiSubmissionsSubmissionIdItemsItemIdTranscriptionPost,
              {
                ...this.ids(i),
                body: { ...body, transcription: this.draft() },
              },
            )
          : this.api.invoke(editFeedbackApiSubmissionsSubmissionIdItemsItemIdFeedbackPost, {
              ...this.ids(i),
              body: { ...body, feedback: this.draft() },
            }),
      field === 'feedback'
        ? 'Uwagi się nie złożą do PDF: sprawdź, czy każdy wzór jest zamknięty między $...$.'
        : undefined,
    );
  }

  protected approve() {
    return this.run(() =>
      this.api.invoke(approveApiSubmissionsSubmissionIdApprovePost, {
        submission_id: this.view()!.submission_id!,
        body: { handed_in_at: this.handedIn() },
      }),
    );
  }

  protected gradeAgain() {
    return this.run(() =>
      this.api.invoke(gradeAgainApiSubmissionsSubmissionIdGradeAgainPost, {
        submission_id: this.view()!.submission_id!,
        body: { handed_in_at: this.handedIn() },
      }),
    );
  }

  private ids(i: ItemView) {
    return { submission_id: this.view()!.submission_id!, item_id: i.item_id };
  }

  private handedIn() {
    return this.view()!.handed_in_at!;
  }

  /** One change through `grading`; afterwards the page shows the Submission as it now is. */
  private async run(change: () => Promise<unknown>, refused = 'Tej zmiany nie można wprowadzić.') {
    this.busy.set(true);
    this.error.set(null);
    try {
      await change();
      this.editing.set(null);
      this.page.reload();
    } catch (e) {
      const status = e instanceof HttpErrorResponse ? e.status : 0;
      this.error.set(
        status === 409
          ? refused
          : status === 404
            ? 'Uczeń oddał w międzyczasie nową wersję pracy. Strona pokazuje ją teraz.'
            : 'Nie udało się zapisać zmiany. Spróbuj jeszcze raz.',
      );
      this.page.reload();
    } finally {
      this.busy.set(false);
    }
  }
}

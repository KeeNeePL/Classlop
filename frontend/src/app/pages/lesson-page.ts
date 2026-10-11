import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, linkedSignal, resource, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { combineLatest, map } from 'rxjs';
import { Api } from '../api/api';
import {
  lessonApiClassesClassIdLessonsLessonIdGet,
  linkAttendeeApiClassesClassIdLessonsLessonIdAttendeesPost,
  overrideApiClassesClassIdLessonsLessonIdAttendanceStudentIdPut,
  refreshApiClassesClassIdLessonsLessonIdRefreshPost,
  setTopicApiClassesClassIdLessonsLessonIdTopicPut,
} from '../api/functions';
import { AttendanceRow } from '../api/models';
import { warsaw } from '../time';
import { Badge } from '../ui/badge';
import { Panel } from '../ui/panel';

type State = NonNullable<AttendanceRow['state']>;

const STATES: { value: State; label: string }[] = [
  { value: 'present', label: 'Obecny' },
  { value: 'late', label: 'Spóźniony' },
  { value: 'absent', label: 'Nieobecny' },
];

/** The Lesson page: its Lesson topic and each Student's Attendance, with the Teacher's overrides. */
@Component({
  imports: [Badge, FormsModule, Panel, RouterLink],
  templateUrl: './lesson-page.html',
  styleUrl: './lesson-page.css',
})
export class LessonPage {
  private readonly api = inject(Api);
  private readonly route = inject(ActivatedRoute);
  // The page sits under `klasy/:klasa`, whose parameter its own route does not inherit.
  private readonly ids = toSignal(
    combineLatest([this.route.parent!.paramMap, this.route.paramMap]).pipe(
      map(([c, l]) => ({ class_id: c.get('klasa') ?? '', lesson_id: l.get('lekcja') ?? '' })),
    ),
    { requireSync: true },
  );

  protected readonly page = resource({
    params: () => this.ids(),
    loader: ({ params }) => this.api.invoke(lessonApiClassesClassIdLessonsLessonIdGet, params),
  });
  protected readonly topic = linkedSignal(() => this.page.value()?.topic ?? '');
  protected readonly links = signal<Record<string, string>>({});
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly states = STATES;
  protected readonly at = warsaw;
  protected readonly back = computed(() => `/klasy/${this.ids().class_id}/lekcje`);
  protected readonly current = computed(
    () => this.page.value()?.students.filter((s) => !s.former) ?? [],
  );

  protected refresh(): Promise<boolean> {
    return this.change(() =>
      this.api.invoke(refreshApiClassesClassIdLessonsLessonIdRefreshPost, this.ids()),
    );
  }

  protected saveTopic(): Promise<boolean> {
    return this.change(() =>
      this.api.invoke(setTopicApiClassesClassIdLessonsLessonIdTopicPut, {
        ...this.ids(),
        body: { topic: this.topic().trim() },
      }),
    );
  }

  /** The Teacher's state for a Student; `null` takes it away. */
  protected override(row: AttendanceRow, state: State | null): Promise<boolean> {
    return this.change(() =>
      this.api.invoke(overrideApiClassesClassIdLessonsLessonIdAttendanceStudentIdPut, {
        ...this.ids(),
        student_id: row.id,
        body: { state },
      }),
    );
  }

  protected link(key: string): Promise<boolean> {
    return this.change(() =>
      this.api.invoke(linkAttendeeApiClassesClassIdLessonsLessonIdAttendeesPost, {
        ...this.ids(),
        body: { key, student_id: this.links()[key] },
      }),
    );
  }

  protected pick(key: string, studentId: string): void {
    this.links.update((l) => ({ ...l, [key]: studentId }));
  }

  private async change(change: () => Promise<unknown>): Promise<boolean> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await change();
      this.page.reload();
      return true;
    } catch (e) {
      this.error.set(
        e instanceof HttpErrorResponse && e.status === 409
          ? 'Teams nie pozwala na tę zmianę. Odśwież stronę i sprawdź stan klasy.'
          : 'Nie udało się zapisać zmiany. Spróbuj jeszcze raz.',
      );
      return false;
    } finally {
      this.busy.set(false);
    }
  }
}

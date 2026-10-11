import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, input, resource, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../api/api';
import {
  cancelBreakApiClassesClassIdBreaksPost,
  changeSlotApiClassesClassIdTimetableChangePost,
  enterTimetableApiClassesClassIdTimetablePost,
  timetableApiClassesClassIdTimetableGet,
} from '../api/functions';
import { Slot, UpcomingLesson } from '../api/models';
import { toInput, warsaw } from '../time';
import { Panel } from '../ui/panel';

const WEEKDAYS = ['poniedziałek', 'wtorek', 'środa', 'czwartek', 'piątek', 'sobota', 'niedziela'];
const DAY = 86_400_000;

/** "08:00:00" or "08:00" as "08:00". */
const hm = (t: string) => t.slice(0, 5);

/** A Lesson's day and time in Warsaw: YYYY-MM-DD as a `date` input has it, and HH:MM. */
const dayOf = (l: UpcomingLesson) => toInput(l.start).slice(0, 10);
const timeOf = (iso: string) => toInput(iso).slice(11, 16);

/** The weekday of a YYYY-MM-DD day, 0 for Monday as in a Slot. */
const weekdayOf = (day: string) => (new Date(`${day}T12:00Z`).getUTCDay() + 6) % 7;
const nextDay = (day: string) =>
  new Date(Date.parse(`${day}T12:00Z`) + DAY).toISOString().slice(0, 10);

const firstSlot = (): Slot => ({ weekday: 0, start: '08:00', end: '08:45' });

/** The Timetable of Ustawienia klasy: weekly slots and the school-year end entered once, then
 * breaks and slot changes, each showing the Lessons it will affect before the Teacher confirms. */
@Component({
  selector: 'cl-timetable',
  imports: [FormsModule, Panel],
  templateUrl: './class-timetable.html',
  styleUrl: './class-timetable.css',
})
export class ClassTimetable {
  private readonly api = inject(Api);
  readonly classId = input.required<string>();
  readonly readOnly = input(false);

  protected readonly timetable = resource({
    params: () => this.classId(),
    loader: ({ params }) =>
      this.api.invoke(timetableApiClassesClassIdTimetableGet, { class_id: params }),
  });
  protected readonly weekdays = WEEKDAYS;
  // Past Lessons keep what they had, so a break or a slot change starts today at the earliest.
  protected readonly today = toInput(new Date().toISOString()).slice(0, 10);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly slots = signal<Slot[]>([firstSlot()]);
  protected readonly yearEnd = signal('');

  protected readonly breakFirst = signal('');
  protected readonly breakLast = signal('');
  /** A break of one day needs only its first. */
  private readonly breakEnd = computed(() => this.breakLast() || this.breakFirst());
  /** The Lessons a break of these dates will cancel. */
  protected readonly inBreak = computed(() => {
    const [first, last] = [this.breakFirst(), this.breakEnd()];
    if (!first || first < this.today || last < first) return [];
    return this.upcoming().filter((l) => first <= dayOf(l) && dayOf(l) <= last);
  });

  protected readonly oldIndex = signal<number | null>(null);
  protected readonly newSlot = signal<Slot>(firstSlot());
  protected readonly changeFrom = signal('');
  private readonly old = computed(() => {
    const at = this.oldIndex();
    return at === null ? undefined : this.timetable.value()?.slots[at];
  });
  /** The old slot's Lessons from that date on, which the new slot replaces. */
  protected readonly replaced = computed(() => {
    const old = this.old();
    const from = this.changeFrom();
    if (!old || !from) return [];
    return this.upcoming().filter(
      (l) =>
        dayOf(l) >= from &&
        weekdayOf(dayOf(l)) === old.weekday &&
        timeOf(l.start) === hm(old.start) &&
        timeOf(l.end) === hm(old.end),
    );
  });
  /** The days of the new slot's Lessons, from that date to the school-year end. */
  protected readonly added = computed(() => {
    const [from, end] = [this.changeFrom(), this.timetable.value()?.school_year_end];
    const days: string[] = [];
    if (!from || !end) return days;
    for (let day = from; day <= end; day = nextDay(day)) {
      if (weekdayOf(day) === this.newSlot().weekday) days.push(day);
    }
    return days;
  });

  protected readonly canEnter = computed(
    () => !!this.yearEnd() && this.slots().length > 0 && this.slots().every((s) => s.start < s.end),
  );
  protected readonly canChange = computed(
    () =>
      !!this.old() && this.changeFrom() >= this.today && this.newSlot().start < this.newSlot().end,
  );

  private readonly upcoming = computed(() =>
    (this.timetable.value()?.lessons ?? []).filter((l) => !l.cancelled),
  );

  protected slotLabel(s: Slot): string {
    return `${WEEKDAYS[s.weekday]} ${hm(s.start)}–${hm(s.end)}`;
  }

  protected lessonLabel(l: UpcomingLesson): string {
    return l.topic ? `${warsaw(l.start)} · ${l.topic}` : warsaw(l.start);
  }

  protected setSlot(at: number, change: Partial<Slot>) {
    this.slots.update((all) => all.map((s, i) => (i === at ? { ...s, ...change } : s)));
  }

  protected setNewSlot(change: Partial<Slot>) {
    this.newSlot.update((s) => ({ ...s, ...change }));
  }

  protected addSlot() {
    this.slots.update((all) => [...all, firstSlot()]);
  }

  protected removeSlot(at: number) {
    this.slots.update((all) => all.filter((_, i) => i !== at));
  }

  protected enter(): Promise<void> {
    return this.change('Ta klasa ma już plan lekcji. Odśwież stronę.', async () => {
      await this.api.invoke(enterTimetableApiClassesClassIdTimetablePost, {
        class_id: this.classId(),
        body: { slots: this.slots(), school_year_end: this.yearEnd() },
      });
      this.slots.set([firstSlot()]);
    });
  }

  protected cancelBreak(): Promise<void> {
    return this.change('Teams nie pozwala odwołać tych lekcji. Odśwież stronę.', async () => {
      await this.api.invoke(cancelBreakApiClassesClassIdBreaksPost, {
        class_id: this.classId(),
        body: { first: this.breakFirst(), last: this.breakEnd() },
      });
      this.breakFirst.set('');
      this.breakLast.set('');
    });
  }

  protected changeSlot(): Promise<void> {
    return this.change('Slot można zmienić od dnia po jego pierwszej lekcji.', async () => {
      await this.api.invoke(changeSlotApiClassesClassIdTimetableChangePost, {
        class_id: this.classId(),
        body: { old: this.old()!, new: this.newSlot(), from_date: this.changeFrom() },
      });
      this.oldIndex.set(null);
      this.changeFrom.set('');
    });
  }

  /** One change through `teams`; afterwards the Timetable shows what Teams now has. A 409 is
   * Teams refusing this change, said in `refused`. */
  private async change(refused: string, change: () => Promise<void>): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await change();
      this.timetable.reload();
    } catch (e) {
      this.error.set(
        e instanceof HttpErrorResponse && e.status === 409
          ? refused
          : e instanceof HttpErrorResponse && e.status === 404
            ? 'Tego już nie ma w Teams. Odśwież stronę.'
            : 'Nie udało się zapisać zmiany. Spróbuj jeszcze raz.',
      );
    } finally {
      this.busy.set(false);
    }
  }
}

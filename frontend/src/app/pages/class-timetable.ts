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

/** A Lesson's day in Warsaw, as a `date` input's YYYY-MM-DD. */
const dayOf = (l: UpcomingLesson) => toInput(l.start).slice(0, 10);

const blank = (): Slot => ({ weekday: 0, start: '08:00', end: '08:45' });

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
  protected readonly warsaw = warsaw;
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly slots = signal<Slot[]>([blank()]);
  protected readonly yearEnd = signal('');

  protected readonly breakFirst = signal('');
  protected readonly breakLast = signal('');
  /** The Lessons a break of these dates will cancel. */
  protected readonly inBreak = computed(() => {
    const [first, last] = [this.breakFirst(), this.breakLast() || this.breakFirst()];
    if (!first || last < first) return [];
    return this.upcoming().filter((l) => first <= dayOf(l) && dayOf(l) <= last);
  });

  protected readonly oldSlot = signal<number | null>(null);
  protected readonly newSlot = signal<Slot>(blank());
  protected readonly changeFrom = signal('');
  /** The Lessons of the old slot from that date, which the new slot's replace. */
  protected readonly replaced = computed(() => {
    const old = this.old();
    const from = this.changeFrom();
    if (!old || !from) return [];
    return this.upcoming().filter(
      (l) =>
        dayOf(l) >= from && this.weekdayOf(l) === old.weekday && this.timeOf(l) === hm(old.start),
    );
  });

  private readonly upcoming = computed(() =>
    (this.timetable.value()?.lessons ?? []).filter((l) => !l.cancelled),
  );

  protected slotLabel(s: Slot): string {
    return `${WEEKDAYS[s.weekday]} ${hm(s.start)}–${hm(s.end)}`;
  }

  protected setSlot(at: number, change: Partial<Slot>) {
    this.slots.update((all) => all.map((s, i) => (i === at ? { ...s, ...change } : s)));
  }

  protected addSlot() {
    this.slots.update((all) => [...all, blank()]);
  }

  protected removeSlot(at: number) {
    this.slots.update((all) => all.filter((_, i) => i !== at));
  }

  protected readonly canEnter = computed(
    () => !!this.yearEnd() && this.slots().length > 0 && this.slots().every((s) => s.start < s.end),
  );

  protected enter(): Promise<void> {
    return this.change(async () => {
      await this.api.invoke(enterTimetableApiClassesClassIdTimetablePost, {
        class_id: this.classId(),
        body: { slots: this.slots(), school_year_end: this.yearEnd() },
      });
      this.slots.set([blank()]);
    });
  }

  protected cancelBreak(): Promise<void> {
    return this.change(async () => {
      await this.api.invoke(cancelBreakApiClassesClassIdBreaksPost, {
        class_id: this.classId(),
        body: { first: this.breakFirst(), last: this.breakLast() || this.breakFirst() },
      });
      this.breakFirst.set('');
      this.breakLast.set('');
    });
  }

  private readonly old = computed(() => {
    const at = this.oldSlot();
    return at === null ? undefined : this.timetable.value()?.slots[at];
  });

  protected readonly canChange = computed(
    () => !!this.old() && !!this.changeFrom() && this.newSlot().start < this.newSlot().end,
  );

  protected changeSlot(): Promise<void> {
    return this.change(async () => {
      await this.api.invoke(changeSlotApiClassesClassIdTimetableChangePost, {
        class_id: this.classId(),
        body: { old: this.old()!, new: this.newSlot(), from_date: this.changeFrom() },
      });
      this.oldSlot.set(null);
      this.changeFrom.set('');
    });
  }

  private weekdayOf(l: UpcomingLesson): number {
    return (new Date(`${dayOf(l)}T12:00Z`).getUTCDay() + 6) % 7;
  }

  private timeOf(l: UpcomingLesson): string {
    return toInput(l.start).slice(11, 16);
  }

  /** One change through `teams`; afterwards the Timetable shows what Teams now has. */
  private async change(change: () => Promise<void>): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await change();
      this.timetable.reload();
    } catch (e) {
      this.error.set(
        e instanceof HttpErrorResponse && e.status === 409
          ? 'Teams nie pozwala na tę zmianę. Slot można zmienić dopiero od dnia po jego pierwszej lekcji.'
          : 'Nie udało się zapisać zmiany. Spróbuj jeszcze raz.',
      );
    } finally {
      this.busy.set(false);
    }
  }
}

/** "08:00:00" or "08:00" as "08:00". */
const hm = (t: string) => t.slice(0, 5);

import { Component, computed, input } from '@angular/core';
import { AssignmentRow } from '../api/models';
import { shortDate, warsaw } from '../time';

type Status = 'scheduled' | 'open' | 'graded';

const LANES: { type: AssignmentRow['type']; label: string }[] = [
  { type: 'exam', label: 'Sprawdzian' },
  { type: 'quiz', label: 'Kartkówka' },
  { type: 'homework', label: 'Praca domowa' },
];

export const STATUS: Record<Status, string> = {
  scheduled: 'Zaplanowana',
  open: 'Zbieranie prac',
  graded: 'Ocenione',
};

const DAY = 86_400_000;

/** When each Assignment was given, on a time axis, in one lane per Assignment type. The mark
 * is an icon of its type coloured by its status; hovering or focusing it shows the details. */
@Component({
  selector: 'cl-assignment-lanes',
  templateUrl: './assignment-lanes.html',
  styleUrl: './assignment-lanes.css',
})
export class AssignmentLanes {
  readonly assignments = input.required<AssignmentRow[]>();
  private readonly now = new Date().toISOString();

  protected readonly lanes = LANES;
  protected readonly statuses = Object.entries(STATUS) as [Status, string][];

  /** The axis spans every given day and today, padded so marks never sit on the edge. */
  private readonly range = computed(() => {
    const times = [...this.assignments().map((a) => Date.parse(a.given_at)), Date.parse(this.now)];
    const from = Math.min(...times) - 3 * DAY;
    const to = Math.max(...times) + 3 * DAY;
    return { from, span: to - from };
  });

  protected readonly at = (iso: string) =>
    ((Date.parse(iso) - this.range().from) / this.range().span) * 100;

  protected readonly ticks = computed(() => {
    const { from, span } = this.range();
    return Array.from({ length: 6 }, (_, i) => {
      const t = from + (span * (i + 0.5)) / 6;
      return { left: ((t - from) / span) * 100, label: shortDate(t) };
    }).filter((t) => Math.abs(t.left - this.today()) > 6);
  });

  protected readonly today = computed(() => this.at(this.now));

  protected readonly marks = (type: AssignmentRow['type']) =>
    this.assignments().filter((a) => a.type === type);

  /** AI grades every Submission as it comes in, so a closed Assignment counts as graded. */
  protected readonly status = (a: AssignmentRow): Status =>
    a.state === 'closed' ? 'graded' : a.state === 'open' ? 'open' : 'scheduled';

  protected readonly statusLabel = (a: AssignmentRow) => STATUS[this.status(a)];
  protected readonly given = (a: AssignmentRow) => shortDate(a.given_at);
  protected readonly due = (a: AssignmentRow) => warsaw(a.due);
  protected readonly label = (a: AssignmentRow) =>
    `${a.title}, zadana ${this.given(a)}, ${this.statusLabel(a)}`;
}

import { Component, computed, inject, resource, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { Api } from '../api/api';
import { overviewApiClassesClassIdOverviewGet } from '../api/functions';
import { AssignmentRow } from '../api/models';
import { warsaw } from '../time';
import { Badge } from '../ui/badge';
import { Invented } from '../ui/invented';
import { LineChart } from '../ui/line-chart';
import { MathText } from '../ui/math';
import { Panel } from '../ui/panel';
import { ProgressBar } from '../ui/progress-bar';

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

/** The Class page's Przegląd tab. */
@Component({
  imports: [Badge, Invented, LineChart, MathText, Panel, ProgressBar, RouterLink],
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

  protected readonly tab = signal<'sections' | 'topics'>('sections');
  protected readonly line = computed(
    () =>
      this.overview()?.average_line.map((p) => ({ at: p.due, percent: p.percent ?? null })) ?? [],
  );

  protected readonly type = (a: AssignmentRow) => TYPE[a.type];
  protected readonly state = (a: AssignmentRow) => STATE[a.state];
  protected readonly due = (a: AssignmentRow) => warsaw(a.due);
  protected readonly link = (student: string) => ['/klasy', this.id(), 'uczniowie', student];
}

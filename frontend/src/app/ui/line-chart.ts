import {
  Component,
  ElementRef,
  OnDestroy,
  computed,
  effect,
  input,
  viewChild,
} from '@angular/core';
import type { ECharts } from 'echarts/core';
import { shortDate } from '../time';

export interface LinePoint {
  /** ISO 8601 UTC */
  at: string;
  /** null leaves a gap, never a zero */
  percent: number | null;
}

/** A percent line over time, drawn by ECharts, which loads on first use. */
@Component({
  selector: 'cl-line-chart',
  template: '<div #canvas></div>',
  host: { role: 'img', '[attr.aria-label]': 'label()' },
  styles: ':host, div { display: block; height: 180px; }',
})
export class LineChart implements OnDestroy {
  readonly points = input.required<LinePoint[]>();
  readonly name = input.required<string>();

  private readonly canvas = viewChild.required<ElementRef<HTMLElement>>('canvas');
  private chart?: Promise<ECharts>;

  protected readonly label = computed(
    () =>
      `${this.name()}: ` +
      this.points()
        .map((p) => `${shortDate(p.at)} ${p.percent === null ? 'brak danych' : p.percent + '%'}`)
        .join(', '),
  );

  constructor() {
    effect(() => {
      const points = this.points();
      const name = this.name();
      this.chart ??= init(this.canvas().nativeElement);
      void this.chart.then((chart) =>
        chart.setOption(
          {
            animation: false,
            grid: { left: 40, right: 16, top: 12, bottom: 24 },
            tooltip: { trigger: 'axis', valueFormatter: (v: unknown) => `${v}%` },
            xAxis: { type: 'time', axisLabel: { formatter: (v: number) => shortDate(v) } },
            yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
            series: [
              {
                name,
                type: 'line',
                data: points.map((p) => [Date.parse(p.at), p.percent]),
                lineStyle: { color: '#2f55d4', width: 2 },
                itemStyle: { color: '#2f55d4' },
              },
            ],
          },
          true,
        ),
      );
    });
  }

  ngOnDestroy(): void {
    void this.chart?.then((chart) => chart.dispose());
  }
}

async function init(host: HTMLElement): Promise<ECharts> {
  const [core, { LineChart }, { GridComponent, TooltipComponent }, { CanvasRenderer }] =
    await Promise.all([
      import('echarts/core'),
      import('echarts/charts'),
      import('echarts/components'),
      import('echarts/renderers'),
    ]);
  core.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer]);
  return core.init(host);
}

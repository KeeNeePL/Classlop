import { Component, ElementRef, effect, input, OnDestroy, viewChild } from '@angular/core';
import type { ECharts } from 'echarts';
import { shortDate } from '../time';

export interface ChartPoint {
  /** ISO 8601 UTC: the point sits at this time on the axis. */
  at: string;
  title: string;
}

export interface Line {
  name: string;
  /** One value per point; null leaves a gap, never a 0. */
  values: (number | null)[];
  faint?: boolean;
}

/** Percent lines over time, drawn with ECharts, which loads on first use. */
@Component({
  selector: 'cl-line-chart',
  template: '<div #box class="box" role="img" [attr.aria-label]="label()"></div>',
  styles: `
    .box {
      width: 100%;
      height: 260px;
    }
  `,
})
export class LineChart implements OnDestroy {
  readonly points = input.required<ChartPoint[]>();
  readonly lines = input.required<Line[]>();
  readonly label = input.required<string>();

  private readonly box = viewChild.required<ElementRef<HTMLDivElement>>('box');
  private chart?: ECharts;
  private readonly resize = () => this.chart?.resize();

  constructor() {
    effect(async () => {
      const points = this.points();
      const lines = this.lines();
      const box = this.box().nativeElement;
      const echarts = await import('echarts');
      this.chart ??= echarts.init(box);
      this.chart.setOption(
        {
          animation: false,
          grid: { left: 40, right: 16, top: 32, bottom: 32 },
          legend: { top: 0 },
          tooltip: {
            trigger: 'axis',
            formatter: (
              params: { dataIndex: number; seriesName: string; value: [string, number | null] }[],
            ) => {
              const point = points[params[0].dataIndex];
              const rows = params.map(
                (p) => `${p.seriesName}: ${p.value[1] == null ? '—' : `${p.value[1]}%`}`,
              );
              return [`${shortDate(point.at)} ${point.title}`, ...rows].join('<br>');
            },
          },
          xAxis: { type: 'time', axisLabel: { formatter: (t: number) => shortDate(t) } },
          yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
          series: lines.map((l) => ({
            name: l.name,
            type: 'line',
            data: l.values.map((v, i) => [points[i].at, v]),
            connectNulls: false,
            symbolSize: l.faint ? 5 : 8,
            lineStyle: { type: l.faint ? 'dashed' : 'solid', opacity: l.faint ? 0.5 : 1 },
            itemStyle: { opacity: l.faint ? 0.5 : 1 },
          })),
        },
        { notMerge: true },
      );
    });
    window.addEventListener('resize', this.resize);
  }

  ngOnDestroy() {
    window.removeEventListener('resize', this.resize);
    this.chart?.dispose();
  }
}

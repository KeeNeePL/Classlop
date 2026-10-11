import { Component, ElementRef, effect, input, OnDestroy, viewChild } from '@angular/core';
import type { ECharts } from 'echarts';

export interface Line {
  name: string;
  /** One value per label; null leaves a gap, never a 0. */
  values: (number | null)[];
  dashed?: boolean;
}

/** Percent lines over the same labels, drawn with ECharts, which loads on first use. */
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
  readonly labels = input.required<string[]>();
  readonly lines = input.required<Line[]>();
  readonly label = input.required<string>();

  private readonly box = viewChild.required<ElementRef<HTMLDivElement>>('box');
  private chart?: ECharts;
  private readonly resize = () => this.chart?.resize();

  constructor() {
    effect(async () => {
      const labels = this.labels();
      const lines = this.lines();
      const box = this.box().nativeElement;
      const echarts = await import('echarts');
      this.chart ??= echarts.init(box);
      this.chart.setOption(
        {
          animation: false,
          grid: { left: 40, right: 16, top: 32, bottom: 48 },
          legend: { top: 0 },
          tooltip: { trigger: 'axis', valueFormatter: (v: unknown) => (v == null ? '—' : `${v}%`) },
          xAxis: { type: 'category', data: labels, axisLabel: { interval: 0, rotate: 20 } },
          yAxis: { type: 'value', min: 0, max: 100, axisLabel: { formatter: '{value}%' } },
          series: lines.map((l) => ({
            name: l.name,
            type: 'line',
            data: l.values,
            connectNulls: false,
            symbolSize: 8,
            lineStyle: { type: l.dashed ? 'dashed' : 'solid' },
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

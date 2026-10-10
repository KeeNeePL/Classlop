import { Component, input } from '@angular/core';
import { ProgressBar } from './progress-bar';

/** A percent as a bar and a number; null is "brak danych", never 0%. */
@Component({
  selector: 'cl-percent',
  imports: [ProgressBar],
  template: `
    <cl-progress [value]="value() ?? 0" />
    @if (value() === null) {
      <span class="muted">brak danych</span>
    } @else {
      <span>{{ value() }}%</span>
    }
  `,
  styles: `
    :host {
      display: flex;
      align-items: center;
      gap: 12px;
      font-variant-numeric: tabular-nums;
    }
    cl-progress {
      flex: 1;
    }
    span {
      min-width: 76px;
      text-align: right;
    }
  `,
})
export class Percent {
  readonly value = input.required<number | null | undefined>();
}

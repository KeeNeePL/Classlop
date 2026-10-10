import { Component, computed, input } from '@angular/core';

@Component({
  selector: 'cl-progress',
  template: '<i [style.width.%]="percent()" [style.background]="color()"></i>',
  styles: `
    :host {
      display: block;
      height: 8px;
      border-radius: 2px;
      background: var(--grid);
      overflow: hidden;
    }
    i {
      display: block;
      height: 100%;
    }
  `,
})
export class ProgressBar {
  /** 0 to 100 */
  readonly value = input.required<number>();
  protected readonly percent = computed(() => Math.max(0, Math.min(100, this.value())));
  protected readonly color = computed(() => `hsl(${this.percent() * 1.2} 65% 45%)`);
}

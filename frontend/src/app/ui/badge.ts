import { Component, input } from '@angular/core';

@Component({
  selector: 'cl-badge',
  template: '<ng-content />',
  host: { '[class]': 'tone()' },
  styles: `
    :host {
      display: inline-block;
      font-size: 11px;
      padding: 1px 7px;
      border-radius: 3px;
      background: var(--grid);
      color: var(--ink);
      white-space: nowrap;
    }
    :host(.live) {
      background: var(--red-soft);
      color: var(--red);
    }
    :host(.warn) {
      background: var(--marker);
      color: var(--ink);
    }
    :host(.danger) {
      background: var(--red-soft);
      color: var(--red);
    }
    :host(.ok) {
      background: #e1f4e8;
      color: #1d6b3c;
    }
  `,
})
export class Badge {
  readonly tone = input<'' | 'live' | 'warn' | 'danger' | 'ok'>('');
}

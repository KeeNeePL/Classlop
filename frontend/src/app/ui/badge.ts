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
      border-radius: 99px;
      background: #eceff3;
      color: #374151;
      white-space: nowrap;
    }
    :host(.live) {
      background: #ffedd5;
      color: var(--live);
    }
    :host(.warn) {
      background: #fef3c7;
      color: #92400e;
    }
    :host(.danger) {
      background: #fee2e2;
      color: #991b1b;
    }
    :host(.ok) {
      background: #dcfce7;
      color: #166534;
    }
  `,
})
export class Badge {
  readonly tone = input<'' | 'live' | 'warn' | 'danger' | 'ok'>('');
}

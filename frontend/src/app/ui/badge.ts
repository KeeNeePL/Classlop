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
      background: #e4eaf6;
      border: 1px solid #b4c0d8;
      color: var(--ink);
      white-space: nowrap;
    }
    :host(.live) {
      border-color: var(--red);
      background: var(--red-soft);
      color: var(--red);
    }
    :host(.warn) {
      border-color: #d8b800;
      background: var(--marker);
      color: var(--ink);
    }
    :host(.danger) {
      border-color: var(--red);
      background: var(--red-soft);
      color: var(--red);
    }
    :host(.ok) {
      border-color: #1d6b3c;
      background: #e1f4e8;
      color: #1d6b3c;
    }
  `,
})
export class Badge {
  readonly tone = input<'' | 'live' | 'warn' | 'danger' | 'ok'>('');
}

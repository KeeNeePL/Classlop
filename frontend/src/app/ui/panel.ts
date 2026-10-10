import { Component } from '@angular/core';

@Component({
  selector: 'cl-panel',
  template: '<ng-content />',
  styles: `
    :host {
      display: block;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 14px 16px;
    }
  `,
})
export class Panel {}

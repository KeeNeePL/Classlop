import { Component } from '@angular/core';

@Component({
  selector: 'cl-panel',
  template: '<ng-content />',
  styles: `
    :host {
      display: block;
      background: var(--card);
      border: 1.5px solid var(--edge);
      border-radius: 4px;
      padding: 16px 18px;
    }
  `,
})
export class Panel {}

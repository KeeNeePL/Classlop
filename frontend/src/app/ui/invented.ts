import { Component } from '@angular/core';

/** Marks a part of a screen that shows invented, hardcoded data. */
@Component({
  selector: 'cl-invented',
  template: 'ZMYŚLONE',
  styles: `
    :host {
      display: inline-block;
      background: #facc15;
      color: #111;
      font-weight: 700;
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 4px;
      letter-spacing: 0.03em;
    }
  `,
})
export class Invented {}

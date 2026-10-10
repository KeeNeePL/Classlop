import { Component } from '@angular/core';

/** Marks a part of a screen that shows invented, hardcoded data. A strip of tape, stuck on
 * slightly crooked. */
@Component({
  selector: 'cl-invented',
  template: 'ZMYŚLONE',
  styles: `
    :host {
      display: inline-block;
      background: var(--tape);
      color: var(--ink);
      font-family: var(--display);
      font-weight: 800;
      font-size: 11px;
      letter-spacing: 0.08em;
      padding: 3px 9px;
      transform: rotate(-2deg);
      box-shadow: 0 1px 0 rgb(22 35 63 / 0.25);
    }
  `,
})
export class Invented {}

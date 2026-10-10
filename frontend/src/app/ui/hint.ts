import { Component, input } from '@angular/core';

let next = 0;

/** A small "i" that explains a number or a section on hover or keyboard focus. */
@Component({
  selector: 'cl-hint',
  template: `
    <button type="button" [attr.aria-describedby]="id" aria-label="Co to znaczy?">i</button>
    <span role="tooltip" [id]="id">{{ text() }}</span>
  `,
  styles: `
    :host {
      position: relative;
      display: inline-block;
      vertical-align: middle;
      margin-left: 8px;
    }
    button {
      display: grid;
      place-items: center;
      width: 18px;
      height: 18px;
      padding: 0;
      border: 0;
      border-radius: 50%;
      background: var(--grid);
      color: var(--muted);
      font: 700 12px/1 var(--display);
      cursor: help;
    }
    button:hover,
    button:focus-visible {
      background: var(--pen);
      color: var(--card);
    }
    span {
      display: none;
      position: absolute;
      z-index: 10;
      top: calc(100% + 10px);
      left: -12px;
      width: 300px;
      padding: 10px 14px;
      background: var(--ink);
      border-radius: 6px;
      box-shadow: 0 8px 24px rgb(22 35 63 / 0.25);
      color: var(--card);
      font:
        400 13px/1.55 'Public Sans Variable',
        system-ui,
        sans-serif;
      letter-spacing: normal;
    }
    /* the arrow, pointing at the "i" */
    span::before {
      content: '';
      position: absolute;
      top: -5px;
      left: 17px;
      width: 10px;
      height: 10px;
      background: var(--ink);
      transform: rotate(45deg);
    }
    :host(:hover) span,
    :host(:focus-within) span {
      display: block;
    }
  `,
})
export class Hint {
  readonly text = input.required<string>();
  protected readonly id = `hint-${next++}`;
}

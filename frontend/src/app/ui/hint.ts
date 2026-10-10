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
      width: 18px;
      height: 18px;
      padding: 0;
      border: 1.5px solid var(--muted);
      border-radius: 50%;
      background: var(--card);
      color: var(--muted);
      font: italic 700 12px/1 var(--display);
      cursor: help;
    }
    button:hover,
    button:focus-visible {
      border-color: var(--pen);
      color: var(--pen);
    }
    span {
      display: none;
      position: absolute;
      z-index: 10;
      top: 26px;
      left: -8px;
      width: 320px;
      padding: 10px 12px;
      background: var(--card);
      border: 1px solid var(--ink);
      border-radius: 4px;
      box-shadow: 3px 3px 0 var(--line);
      color: var(--ink);
      font:
        400 13px/1.45 'Public Sans Variable',
        system-ui,
        sans-serif;
      letter-spacing: normal;
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

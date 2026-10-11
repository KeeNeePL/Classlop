import { Component, input } from '@angular/core';
import { Hint } from './hint';

/** Marks a screen that still shows invented, hardcoded data: an "i" saying which parts are real
 * and which are invented. */
@Component({
  selector: 'cl-invented',
  imports: [Hint],
  template: '<cl-hint class="end" label="Skąd te dane?" [text]="text()" />',
})
export class Invented {
  readonly text = input.required<string>();
}

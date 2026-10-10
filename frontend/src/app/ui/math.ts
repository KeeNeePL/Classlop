import { Component, computed, inject, input } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import katex from 'katex';

interface Part {
  text: string;
  html?: SafeHtml;
}

/** Text with inline LaTeX between dollar signs. KaTeX renders the formulas; everything else is
 * escaped by the template. The one place where Student text (Transcriptions) is rendered. */
@Component({
  selector: 'cl-math',
  template: `@for (part of parts(); track $index) {
    @if (part.html) {
      <span [innerHTML]="part.html"></span>
    } @else {
      <span>{{ part.text }}</span>
    }
  }`,
  styles: ':host { white-space: pre-wrap; }',
})
export class MathText {
  private readonly sanitizer = inject(DomSanitizer);
  readonly text = input.required<string>();

  protected readonly parts = computed<Part[]>(() =>
    this.text()
      .split(/\$([^$]+)\$/)
      .map((piece, i) =>
        i % 2 === 0
          ? { text: piece }
          : {
              text: piece,
              // KaTeX output is its own escaped markup; the sanitizer would strip its styles.
              html: this.sanitizer.bypassSecurityTrustHtml(
                katex.renderToString(piece, { throwOnError: false }),
              ),
            },
      )
      .filter((part) => part.text),
  );
}

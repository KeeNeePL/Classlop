import { Component, computed, inject, input } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import katex from 'katex';

interface Part {
  text: string;
  html?: SafeHtml;
}

// Display math ($$...$$ or \[...\]) takes the line breaks around it, since it sits on its own
// line anyway; inline math is $...$ or \(...\).
const FORMULA = /\n?(?:\$\$([^$]+)\$\$|\\\[([\s\S]+?)\\\])\n?|\$([^$]+)\$|\\\(([\s\S]+?)\\\)/g;

/** Text with LaTeX formulas. KaTeX renders the formulas; everything else is escaped by the
 * template. The one place where Student text (Transcriptions) is rendered. */
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

  protected readonly parts = computed<Part[]>(() => {
    const text = this.text();
    const parts: Part[] = [];
    let at = 0;
    for (const m of text.matchAll(FORMULA)) {
      const display = m[1] ?? m[2];
      const formula = display ?? m[3] ?? m[4];
      parts.push(
        { text: text.slice(at, m.index) },
        { text: formula, html: this.render(formula, display !== undefined) },
      );
      at = m.index + m[0].length;
    }
    parts.push({ text: text.slice(at) });
    return parts.filter((part) => part.text);
  });

  private render(formula: string, displayMode: boolean): SafeHtml {
    // KaTeX output is its own escaped markup; the sanitizer would strip its styles.
    return this.sanitizer.bypassSecurityTrustHtml(
      katex.renderToString(formula, { displayMode, throwOnError: false }),
    );
  }
}

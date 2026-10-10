import { Component, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

/** A route that exists before its screen does; the title comes from the route's data. */
@Component({
  template: `
    @if (data.sub) {
      <h2>{{ data.title }}</h2>
    } @else {
      <h1>{{ data.title }}</h1>
    }
    <p class="muted">Ta strona jest jeszcze pusta.</p>
  `,
})
export class EmptyPage {
  protected readonly data = inject(ActivatedRoute).snapshot.data as {
    title: string;
    sub?: boolean;
  };
}

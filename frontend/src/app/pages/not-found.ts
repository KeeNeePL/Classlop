import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  imports: [RouterLink],
  template: `
    <h1>Nie ma takiej strony</h1>
    <p class="muted"><a routerLink="/">Wróć do listy Do zrobienia</a></p>
  `,
})
export class NotFound {}

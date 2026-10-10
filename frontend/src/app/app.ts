import { Component, inject, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { Api } from './api/api';
import { meApiMeGet } from './api/functions';

@Component({
  imports: [RouterOutlet],
  selector: 'app-root',
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App {
  protected readonly name = signal<string | null>(null);

  constructor() {
    inject(Api)
      .invoke(meApiMeGet)
      .then((me) => this.name.set(me.name));
  }
}

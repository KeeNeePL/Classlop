import { Component, inject, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { Api } from './api/api';
import { meApiMeGet } from './api/functions';
import { HomeStore } from './shell/home-store';
import { Sidebar } from './shell/sidebar';

@Component({
  imports: [RouterOutlet, Sidebar],
  selector: 'app-root',
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App {
  protected readonly name = signal<string | null>(null);
  protected readonly signInLapsed = signal(false);

  constructor() {
    const home = inject(HomeStore);
    inject(Api)
      .invoke(meApiMeGet)
      .then((me) => {
        this.name.set(me.name);
        this.signInLapsed.set(me.sign_in_lapsed);
        return home.refresh();
      });
  }
}

import { Component, inject, input } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { HomeStore } from './home-store';

@Component({
  selector: 'cl-sidebar',
  imports: [RouterLink, RouterLinkActive],
  templateUrl: './sidebar.html',
  styleUrl: './sidebar.css',
})
export class Sidebar {
  protected readonly home = inject(HomeStore).home;
  readonly name = input<string | null>(null);
}

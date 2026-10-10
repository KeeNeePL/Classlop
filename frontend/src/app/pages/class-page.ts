import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { map } from 'rxjs';
import { HomeStore } from '../shell/home-store';

@Component({
  imports: [RouterLink, RouterLinkActive, RouterOutlet],
  template: `
    <h1>Klasa {{ name() }}</h1>
    <div class="tabs">
      <a [routerLink]="base()" routerLinkActive="on" [routerLinkActiveOptions]="{ exact: true }"
        >Przegląd</a
      >
      <a [routerLink]="[base(), 'lekcje']" routerLinkActive="on">Lekcje</a>
      <a [routerLink]="[base(), 'ustawienia']" routerLinkActive="on">Ustawienia klasy</a>
    </div>
    <router-outlet />
  `,
  styles: `
    .tabs {
      display: flex;
      gap: 6px;
      margin: 14px 0;
    }
    .tabs a {
      padding: 4px 12px;
      border: 1px solid var(--line);
      border-radius: 99px;
      background: var(--panel);
    }
    .tabs a.on {
      border-color: var(--accent);
    }
  `,
})
export class ClassPage {
  private readonly id = toSignal(
    inject(ActivatedRoute).paramMap.pipe(map((p) => p.get('klasa') ?? '')),
    {
      requireSync: true,
    },
  );
  private readonly home = inject(HomeStore).home;

  protected readonly base = computed(() => `/klasy/${this.id()}`);
  protected readonly name = computed(
    () => this.home()?.classes.find((c) => c.id === this.id())?.name ?? this.id().toUpperCase(),
  );
}

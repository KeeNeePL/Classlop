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
      gap: 24px;
      margin: 20px 0 24px;
      border-bottom: 1.5px solid var(--ink);
    }
    .tabs a {
      padding: 6px 0;
      margin-bottom: -1.5px;
      color: var(--muted);
      font-weight: 600;
      border-bottom: 3px solid transparent;
    }
    .tabs a.on {
      color: var(--ink);
      border-bottom-color: var(--pen);
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

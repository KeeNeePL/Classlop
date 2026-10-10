import { Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Entry } from '../api/models';
import { HomeStore } from '../shell/home-store';
import { today, warsaw } from '../time';
import { Invented } from '../ui/invented';

const LESSONS: Entry['kind'][] = ['live_lesson', 'next_lesson'];
const PROBLEMS: Entry['kind'][] = ['sign_in', 'give_failed', 'team_removed'];

@Component({
  imports: [RouterLink, Invented],
  templateUrl: './do-zrobienia.html',
  styleUrl: './do-zrobienia.css',
})
export class DoZrobienia {
  protected readonly home = inject(HomeStore).home;
  protected readonly today = today();
  protected readonly count = computed(() => this.home()?.entries.length ?? 0);

  protected icon(entry: Entry): string {
    return PROBLEMS.includes(entry.kind) ? '!' : LESSONS.includes(entry.kind) ? 'LEK' : 'PRA';
  }

  protected tone(entry: Entry): string {
    return entry.kind === 'live_lesson'
      ? 'live'
      : PROBLEMS.includes(entry.kind)
        ? 'problem'
        : 'work';
  }

  protected external(entry: Entry): boolean {
    return entry.link.startsWith('/auth/');
  }

  protected at(entry: Entry): string {
    return entry.at ? warsaw(entry.at) : '';
  }
}

import { Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Entry } from '../api/models';
import { HomeStore } from '../shell/home-store';
import { today, warsaw } from '../time';

const MARK: Record<Entry['kind'], { icon: string; tone: string }> = {
  live_lesson: { icon: 'LEK', tone: 'live' },
  next_lesson: { icon: 'LEK', tone: 'work' },
  sign_in: { icon: '!', tone: 'problem' },
  give_failed: { icon: '!', tone: 'problem' },
  team_removed: { icon: '!', tone: 'problem' },
  graded: { icon: 'PRA', tone: 'work' },
  deadline: { icon: 'PRA', tone: 'work' },
};

@Component({
  imports: [RouterLink],
  templateUrl: './do-zrobienia.html',
  styleUrl: './do-zrobienia.css',
})
export class DoZrobienia {
  protected readonly home = inject(HomeStore).home;
  protected readonly today = today();
  protected readonly mark = (entry: Entry) => MARK[entry.kind];

  protected external(entry: Entry): boolean {
    return entry.link.startsWith('/auth/');
  }

  protected at(entry: Entry): string {
    return entry.at ? warsaw(entry.at) : '';
  }
}

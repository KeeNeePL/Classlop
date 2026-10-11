import { Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../api/api';
import { answerQuestionApiCalendarQuestionsQuestionIdPost } from '../api/functions';
import { Entry } from '../api/models';
import { HomeStore } from '../shell/home-store';
import { today, warsaw } from '../time';

const MARK: Record<Entry['kind'], { icon: string; tone: string }> = {
  live_lesson: { icon: 'LEK', tone: 'live' },
  next_lesson: { icon: 'LEK', tone: 'work' },
  sign_in: { icon: '!', tone: 'problem' },
  give_failed: { icon: '!', tone: 'problem' },
  team_removed: { icon: '!', tone: 'problem' },
  calendar_question: { icon: '?', tone: 'work' },
  graded: { icon: 'PRA', tone: 'work' },
  deadline: { icon: 'PRA', tone: 'work' },
};

@Component({
  imports: [RouterLink],
  templateUrl: './do-zrobienia.html',
  styleUrl: './do-zrobienia.css',
})
export class DoZrobienia {
  private readonly api = inject(Api);
  private readonly store = inject(HomeStore);
  protected readonly home = this.store.home;
  protected readonly today = today();
  protected readonly mark = (entry: Entry) => MARK[entry.kind];

  protected async answer(id: string, answer: string): Promise<void> {
    await this.api.invoke(answerQuestionApiCalendarQuestionsQuestionIdPost, {
      question_id: id,
      body: { answer },
    });
    await this.store.refresh();
  }

  /** Signing in and joining a Lesson in Teams leave the app. */
  protected external(entry: Entry): boolean {
    return ['/auth/', 'https://'].some((start) => entry.link?.startsWith(start));
  }

  protected at(entry: Entry): string {
    return entry.at ? warsaw(entry.at) : '';
  }
}

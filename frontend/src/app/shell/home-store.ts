import { Injectable, effect, inject, signal, untracked } from '@angular/core';
import { Api } from '../api/api';
import { homeApiHomeGet } from '../api/functions';
import { Home } from '../api/models';
import { EventStream, StreamEvent } from './event-stream';

/** What the queue and the sidebar show, so a job finishing in these changes them. */
const CONCERNS: StreamEvent['kind'][] = ['hand_in', 'graded', 'attendance'];

/** The sidebar and the Do zrobienia queue, from the one home endpoint. */
@Injectable({ providedIn: 'root' })
export class HomeStore {
  private readonly api = inject(Api);
  readonly home = signal<Home | null>(null);

  constructor() {
    const stream = inject(EventStream);
    for (const kind of CONCERNS) {
      const event = stream.of(kind);
      effect(() => {
        if (event()) untracked(() => void this.refresh());
      });
    }
  }

  async refresh(): Promise<void> {
    this.home.set(await this.api.invoke(homeApiHomeGet));
  }
}

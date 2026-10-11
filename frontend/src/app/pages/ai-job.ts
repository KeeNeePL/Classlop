import { Component, computed, inject, input, output, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../api/api';
import {
  dropDuplicateApiChatsDuplicatesPendingIdDropPost,
  retireApiBankItemsItemIdRetirePost,
  uploadAnywayApiChatsDuplicatesPendingIdUploadPost,
} from '../api/functions';
import { JobCard, NumberedItem, PendingDuplicate } from '../api/models';
import { Badge } from '../ui/badge';
import { MathText } from '../ui/math';
import { ProgressBar } from '../ui/progress-bar';
import { DIFFICULTY } from './bank-store';

interface Step {
  label: string;
  state: 'done' | 'now' | 'todo' | 'failed';
}

type Counts = Record<string, number | undefined>;

/** What a Chat's job looks like in the conversation: its steps as they go, then the Items it
 * added, and for an upload the near-duplicates that wait for the Teacher. */
@Component({
  selector: 'cl-ai-job',
  imports: [Badge, MathText, ProgressBar, RouterLink],
  templateUrl: './ai-job.html',
  styleUrl: './ai-job.css',
})
export class AiJob {
  private readonly api = inject(Api);
  readonly job = input.required<JobCard>();
  /** The job's Items or near-duplicates changed; the screen reads them again. */
  readonly changed = output<void>();

  protected readonly difficulty = DIFFICULTY;
  protected readonly busy = signal(false);

  protected readonly title = computed(() =>
    this.job().kind === 'upload' ? `Plik ${this.job().filename ?? ''}`.trim() : 'Generowanie zadań',
  );

  /** How far the job is: what is done out of what there is, once the job knows. */
  private readonly counts = computed(() => {
    const p = (this.job().progress ?? {}) as Counts;
    return this.job().kind === 'upload'
      ? { done: p['pages_done'], total: p['pages'] }
      : { done: p['landed'], total: p['total'] };
  });

  /** 0 to 100, or nothing before the job knows its size. */
  protected readonly percent = computed(() => {
    const { done, total } = this.counts();
    return total ? Math.round(((done ?? 0) / total) * 100) : null;
  });

  protected readonly steps = computed<Step[]>(() => {
    const { kind, status } = this.job();
    const { done, total } = this.counts();
    const counted = total ? ` (${done ?? 0} z ${total})` : '';
    const waiting = status === 'queued' || status === 'waiting_for_sign_in';
    const working = status === 'failed' ? 'failed' : status === 'running' ? 'now' : 'done';
    return [
      {
        label: status === 'waiting_for_sign_in' ? 'Czeka na zalogowanie do Teams' : 'W kolejce',
        state: waiting ? 'now' : 'done',
      },
      {
        label: (kind === 'upload' ? 'Odczyt stron' : 'Pisanie zadań') + counted,
        state: waiting ? 'todo' : working,
      },
      {
        label: status === 'failed' ? 'Nie udało się' : 'Gotowe',
        state: status === 'succeeded' ? 'done' : status === 'failed' ? 'failed' : 'todo',
      },
    ];
  });

  protected readonly options = (card: NumberedItem) =>
    Object.entries(card.item.version.options ?? {});

  protected retire(card: NumberedItem): Promise<void> {
    return this.run(() =>
      this.api.invoke(retireApiBankItemsItemIdRetirePost, { item_id: card.item.id }),
    );
  }

  protected decide(pending: PendingDuplicate, keep: boolean): Promise<void> {
    const params = { pending_id: pending.id };
    return this.run(() =>
      keep
        ? this.api.invoke(uploadAnywayApiChatsDuplicatesPendingIdUploadPost, params)
        : this.api.invoke(dropDuplicateApiChatsDuplicatesPendingIdDropPost, params),
    );
  }

  private async run(action: () => Promise<unknown>): Promise<void> {
    this.busy.set(true);
    try {
      await action();
    } finally {
      this.busy.set(false);
      this.changed.emit();
    }
  }
}

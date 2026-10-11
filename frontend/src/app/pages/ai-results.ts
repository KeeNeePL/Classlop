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
import { jobFinished, jobPercent, jobSteps, jobTitle } from './ai-progress';
import { DIFFICULTY } from './bank-store';

/** What a Chat has produced, beside the conversation: the jobs still at work, the near-duplicates
 * that wait for the Teacher, and every Item the Chat's jobs added. */
@Component({
  selector: 'cl-ai-results',
  imports: [Badge, MathText, ProgressBar, RouterLink],
  templateUrl: './ai-results.html',
  styleUrl: './ai-results.css',
})
export class AiResults {
  private readonly api = inject(Api);
  readonly jobs = input.required<JobCard[]>();
  /** An Item or a near-duplicate changed; the screen reads the jobs again. */
  readonly changed = output<void>();

  protected readonly difficulty = DIFFICULTY;
  protected readonly title = jobTitle;
  protected readonly steps = jobSteps;
  protected readonly percent = jobPercent;
  protected readonly busy = signal(false);
  /** The Item the Teacher is asked to confirm removing. */
  protected readonly confirming = signal<string | null>(null);

  protected readonly working = computed(() => this.jobs().filter((j) => !jobFinished(j)));
  protected readonly pending = computed(() => this.jobs().flatMap((j) => j.pending ?? []));
  protected readonly items = computed(() =>
    this.jobs()
      .flatMap((j) => j.items)
      .sort((a, b) => a.number - b.number),
  );

  protected readonly options = (card: NumberedItem) =>
    Object.entries(card.item.version.options ?? {});

  protected retire(card: NumberedItem): Promise<void> {
    this.confirming.set(null);
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

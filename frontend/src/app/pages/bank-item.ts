import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, linkedSignal, resource, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { Api } from '../api/api';
import {
  detailApiBankItemsItemIdGet,
  dismissFlagApiBankItemsItemIdDismissFlagPost,
  editApiBankItemsItemIdPatch,
  restoreApiBankItemsItemIdRestorePost,
  retireApiBankItemsItemIdRetirePost,
} from '../api/functions';
import { ItemChanges, ItemDetail, ItemVersion } from '../api/models';
import { HomeStore } from '../shell/home-store';
import { shortDate } from '../time';
import { Badge } from '../ui/badge';
import { MathText } from '../ui/math';
import { Panel } from '../ui/panel';
import { Percent } from '../ui/percent';
import { BankStore, DIFFICULTY } from './bank-store';

const REQUIREMENTS: ItemVersion['general_requirements'] = ['I', 'II', 'III', 'IV'];

/** What the Edit form holds while the Teacher types. */
interface Draft {
  text: string;
  points: number;
  difficulty: ItemVersion['difficulty'];
  general: string[];
  topics: string[];
  options: { key: string; text: string }[];
  correct: string[];
  answer: string;
  solution: string;
  rubric: { points: number; description: string }[];
}

const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);
const sorted = (list: string[]): string[] => [...list].sort();

function draftOf(v: ItemVersion): Draft {
  return {
    text: v.text,
    points: v.points,
    difficulty: v.difficulty,
    general: [...v.general_requirements],
    topics: v.curriculum_topics.map((t) => t.id),
    options: Object.entries(v.options ?? {}).map(([key, text]) => ({ key, text })),
    correct: [...(v.correct_options ?? [])],
    answer: v.answer ?? '',
    solution: v.model_solution ?? '',
    rubric: (v.rubric ?? []).map((r) => ({ ...r })),
  };
}

/** What the Teacher changed; what is left out stays as it was. */
function changesOf(d: Draft, v: ItemVersion): ItemChanges {
  const c: ItemChanges = {};
  if (d.text !== v.text) c.text = d.text;
  if (d.points !== v.points) c.points = d.points;
  if (d.difficulty !== v.difficulty) c.difficulty = d.difficulty;
  if (!same(sorted(d.general), sorted(v.general_requirements))) {
    c.general_requirements = d.general as ItemVersion['general_requirements'];
  }
  if (!same(sorted(d.topics), sorted(v.curriculum_topics.map((t) => t.id)))) {
    c.curriculum_topic_ids = d.topics;
  }
  if (v.item_format === 'closed') {
    const options = Object.fromEntries(d.options.map((o) => [o.key, o.text]));
    if (!same(options, v.options)) c.options = options;
    if (!same(sorted(d.correct), sorted(v.correct_options ?? []))) c.correct_options = d.correct;
  } else {
    if (d.answer !== (v.answer ?? '')) c.answer = d.answer;
    if (d.solution !== (v.model_solution ?? '')) c.model_solution = d.solution;
    if (!same(d.rubric, v.rubric)) c.rubric = d.rubric;
  }
  return c;
}

function messageOf(error: unknown): string {
  const detail = error instanceof HttpErrorResponse ? error.error?.detail : null;
  return typeof detail === 'string' ? detail : 'Nie udało się zapisać zmian.';
}

/** One Item of the bank: what it says, where it was used, and what the Teacher can do to it. */
@Component({
  imports: [Badge, FormsModule, MathText, Panel, Percent, RouterLink],
  templateUrl: './bank-item.html',
  styleUrl: './bank-item.css',
})
export class BankItem {
  private readonly api = inject(Api);
  private readonly bank = inject(BankStore);
  private readonly home = inject(HomeStore);
  private readonly router = inject(Router);
  private readonly id = toSignal(
    inject(ActivatedRoute).paramMap.pipe(map((p) => p.get('zadanie') ?? '')),
    { requireSync: true },
  );

  protected readonly detail = resource({
    params: () => this.id(),
    loader: ({ params }) => this.api.invoke(detailApiBankItemsItemIdGet, { item_id: params }),
  });

  // Each of these starts afresh when the Teacher opens another Item.
  protected readonly draft = linkedSignal<string, Draft | null>({
    source: this.id,
    computation: () => null,
  });
  protected readonly offer = linkedSignal<string, boolean>({
    source: this.id,
    computation: () => false,
  });
  protected readonly error = linkedSignal<string, string | null>({
    source: this.id,
    computation: () => null,
  });
  protected readonly confirming = linkedSignal<string, boolean>({
    source: this.id,
    computation: () => false,
  });
  protected readonly busy = signal(false);

  protected readonly sections = computed(() => this.bank.filters()?.sections ?? []);
  protected readonly requirements = REQUIREMENTS;
  protected readonly levels = Object.keys(DIFFICULTY) as ItemVersion['difficulty'][];
  protected readonly difficulty = DIFFICULTY;
  protected readonly date = shortDate;
  protected readonly options = (v: ItemVersion) => Object.entries(v.options ?? {});
  protected readonly percent = (average: number) => Math.round(average * 100);

  protected edit(d: ItemDetail): void {
    this.error.set(null);
    this.draft.set(draftOf(d.item.version));
  }

  protected cancel(): void {
    this.draft.set(null);
    this.error.set(null);
  }

  protected has(list: string[], value: string): boolean {
    return list.includes(value);
  }

  protected toggle(list: string[], value: string, on: boolean): void {
    const at = list.indexOf(value);
    if (on && at < 0) list.push(value);
    if (!on && at >= 0) list.splice(at, 1);
  }

  protected addLevel(d: Draft): void {
    const top = d.rubric.at(-1)?.points ?? 0;
    d.rubric.push({ points: Math.min(top + 1, d.points), description: '' });
  }

  protected async save(current: ItemDetail): Promise<void> {
    const draft = this.draft();
    if (!draft) return;
    if (!draft.topics.length || !draft.general.length) {
      this.error.set('Zadanie potrzebuje tematu i wymagania ogólnego.');
      return;
    }
    const changes = changesOf(draft, current.item.version);
    if (!Object.keys(changes).length) {
      this.cancel();
      return;
    }
    await this.run(async () => {
      const result = await this.api.invoke(editApiBankItemsItemIdPatch, {
        item_id: current.item.id,
        body: changes,
      });
      this.detail.set(result.detail);
      this.offer.set(result.offer_regenerate);
      this.draft.set(null);
    });
  }

  /** Deleting takes the Item out of the bank; the Assignments that used it keep it. */
  protected async remove(d: ItemDetail): Promise<void> {
    await this.run(async () => {
      await this.api.invoke(retireApiBankItemsItemIdRetirePost, { item_id: d.item.id });
    });
    if (!this.error()) await this.router.navigate(['/bank']);
  }

  protected restore(d: ItemDetail): Promise<void> {
    return this.act(restoreApiBankItemsItemIdRestorePost, d);
  }

  protected dismiss(d: ItemDetail): Promise<void> {
    return this.act(dismissFlagApiBankItemsItemIdDismissFlagPost, d);
  }

  private act(call: typeof retireApiBankItemsItemIdRetirePost, d: ItemDetail): Promise<void> {
    return this.run(async () => {
      this.detail.set(await this.api.invoke(call, { item_id: d.item.id }));
    });
  }

  /** Runs a change, then brings the list and the sidebar's Flagged count up to date. */
  private async run(change: () => Promise<void>): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await change();
      this.bank.refresh();
      await this.home.refresh();
    } catch (e) {
      this.error.set(messageOf(e));
    } finally {
      this.busy.set(false);
    }
  }
}

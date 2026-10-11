import { Component, computed, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Item } from '../api/models';
import { Badge } from '../ui/badge';
import { MathText } from '../ui/math';
import { Panel } from '../ui/panel';
import { TopicPicker } from './topic-picker';
import { BankStore, DIFFICULTY, SIZE } from './bank-store';

/** The Bank zadań: search and filters on the left, the chosen Item on the right. */
@Component({
  imports: [Badge, MathText, Panel, RouterLink, RouterLinkActive, RouterOutlet, TopicPicker],
  templateUrl: './bank.html',
  styleUrl: './bank.css',
})
export class Bank {
  protected readonly store = inject(BankStore);
  protected readonly difficulty = DIFFICULTY;
  protected readonly levels = Object.keys(DIFFICULTY) as Item['version']['difficulty'][];
  protected readonly criteria = this.store.criteria;
  protected readonly pages = computed(() =>
    Math.max(1, Math.ceil((this.store.results()?.total ?? 0) / SIZE)),
  );
  private typing: ReturnType<typeof setTimeout> | undefined;

  /** What the list is narrowed to, as chips: a whole section as one, otherwise each topic. */
  protected readonly chosen = computed(() => {
    const picked = new Set(this.criteria().topics);
    const chips: { id: string; name: string; ids: string[] }[] = [];
    for (const s of this.store.filters()?.sections ?? []) {
      const ids = s.topics.map((t) => t.id).filter((id) => picked.has(id));
      if (ids.length && ids.length === s.topics.length) chips.push({ id: s.id, name: s.name, ids });
      else for (const t of s.topics) if (picked.has(t.id)) chips.push({ ...t, ids: [t.id] });
    }
    return chips;
  });

  /** Searches a moment after the Teacher stops typing. */
  protected type(q: string): void {
    clearTimeout(this.typing);
    this.typing = setTimeout(() => this.store.change({ q }), 250);
  }

  protected toggleLevel(level: Item['version']['difficulty']): void {
    const now = this.criteria().difficulty;
    this.store.change({
      difficulty: now.includes(level) ? now.filter((d) => d !== level) : [...now, level],
    });
  }

  protected setNeverUsedWith(event: Event): void {
    this.store.change({ neverUsedWith: (event.target as HTMLSelectElement).value || null });
  }

  /** Takes topics off the list, as the chips do. */
  protected drop(ids: string[]): void {
    this.store.change({ topics: this.criteria().topics.filter((id) => !ids.includes(id)) });
  }
}

/** The right-hand side of the bank before an Item is chosen. */
@Component({
  imports: [Panel],
  template: '<cl-panel><p>Wybierz zadanie z listy.</p></cl-panel>',
  styles: 'p { margin: 0; }',
})
export class BankEmpty {}

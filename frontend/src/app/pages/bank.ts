import { Component, computed, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Item } from '../api/models';
import { Badge } from '../ui/badge';
import { MathText } from '../ui/math';
import { Panel } from '../ui/panel';
import { BankStore, DIFFICULTY, SIZE } from './bank-store';

/** The Bank zadań: search and filters on the left, the chosen Item on the right. */
@Component({
  imports: [Badge, MathText, Panel, RouterLink, RouterLinkActive, RouterOutlet],
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

  /** What the Teacher types to find a Curriculum topic in the full-screen list. */
  protected readonly topicQuery = signal('');

  /** The sections with the topics that fit the words typed; a section that fits keeps all. */
  protected readonly sections = computed(() => {
    const words = this.topicQuery().trim().toLowerCase();
    const all = this.store.filters()?.sections ?? [];
    if (!words) return all;
    return all
      .map((s) =>
        s.name.toLowerCase().includes(words)
          ? s
          : { ...s, topics: s.topics.filter((t) => t.name.toLowerCase().includes(words)) },
      )
      .filter((s) => s.topics.length);
  });

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

  protected openTopics(dialog: HTMLDialogElement): void {
    this.topicQuery.set('');
    dialog.showModal();
  }

  protected picked(id: string): boolean {
    return this.criteria().topics.includes(id);
  }

  /** How many of a section's topics are picked: all, some or none. */
  protected share(topics: { id: string }[]): 'all' | 'some' | 'none' {
    const n = topics.filter((t) => this.picked(t.id)).length;
    return n === 0 ? 'none' : n === topics.length ? 'all' : 'some';
  }

  protected topicIds(topics: { id: string }[]): string[] {
    return topics.map((t) => t.id);
  }

  protected pickTopics(ids: string[], on: boolean): void {
    const rest = this.criteria().topics.filter((id) => !ids.includes(id));
    this.store.change({ topics: on ? [...rest, ...ids] : rest });
  }

  protected clearTopics(): void {
    this.store.change({ topics: [] });
  }
}

/** The right-hand side of the bank before an Item is chosen. */
@Component({
  imports: [Panel],
  template: '<cl-panel><p>Wybierz zadanie z listy.</p></cl-panel>',
  styles: 'p { margin: 0; }',
})
export class BankEmpty {}

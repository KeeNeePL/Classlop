import { Component, computed, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Item } from '../api/models';
import { Badge } from '../ui/badge';
import { MathText } from '../ui/math';
import { BankStore, Criteria, DIFFICULTY, FORMAT, SIZE } from './bank-store';

/** The Bank zadań: search and filters on the left, the chosen Item on the right. */
@Component({
  imports: [Badge, MathText, RouterLink, RouterLinkActive, RouterOutlet],
  templateUrl: './bank.html',
  styleUrl: './bank.css',
})
export class Bank {
  protected readonly store = inject(BankStore);
  protected readonly difficulty = DIFFICULTY;
  protected readonly format = FORMAT;
  protected readonly levels = Object.keys(DIFFICULTY) as Item['version']['difficulty'][];
  protected readonly criteria = this.store.criteria;
  protected readonly pages = computed(() =>
    Math.max(1, Math.ceil((this.store.results()?.total ?? 0) / SIZE)),
  );
  private typing: ReturnType<typeof setTimeout> | undefined;

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

  protected setFormat(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.store.change({ format: (value || null) as Criteria['format'] });
  }

  protected setNeverUsedWith(event: Event): void {
    this.store.change({ neverUsedWith: (event.target as HTMLSelectElement).value || null });
  }
}

/** The right-hand side of the bank before an Item is chosen. */
@Component({ template: '<p class="muted">Wybierz zadanie z listy.</p>' })
export class BankEmpty {}

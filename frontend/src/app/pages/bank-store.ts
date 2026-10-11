import { Injectable, inject, linkedSignal, resource, signal } from '@angular/core';
import { Api } from '../api/api';
import { filtersApiBankFiltersGet, searchApiBankItemsGet } from '../api/functions';
import { Item, SearchPage } from '../api/models';

type Difficulty = Item['version']['difficulty'];

/** What narrows the Bank zadań list. */
export interface Criteria {
  q: string;
  /** Curriculum topic ids; an Item with any of them fits. */
  topics: string[];
  difficulty: Difficulty[];
  neverUsedWith: string | null;
  page: number;
}

export const SIZE = 20;

export const DIFFICULTY: Record<Item['version']['difficulty'], string> = {
  easy: 'łatwe',
  medium: 'średnie',
  hard: 'trudne',
};

const NONE: Criteria = {
  q: '',
  topics: [],
  difficulty: [],
  neverUsedWith: null,
  page: 1,
};

/** The bank's search and filters, kept while the Teacher moves between Items. */
@Injectable({ providedIn: 'root' })
export class BankStore {
  private readonly api = inject(Api);
  readonly criteria = signal<Criteria>(NONE);
  readonly filters = resource({ loader: () => this.api.invoke(filtersApiBankFiltersGet) }).value;

  private readonly found = resource({
    params: () => this.criteria(),
    loader: ({ params: c }) =>
      this.api.invoke(searchApiBankItemsGet, {
        q: c.q,
        topic: c.topics,
        difficulty: c.difficulty,
        never_used_with_class: c.neverUsedWith,
        page: c.page,
        size: SIZE,
      }),
  });

  /** The latest page found, kept on screen while the next one loads. */
  readonly results = linkedSignal<SearchPage | undefined, SearchPage | undefined>({
    source: () => this.found.value(),
    computation: (page, previous) => page ?? previous?.value,
  });

  /** Changing what is searched goes back to the first page. */
  change(patch: Partial<Criteria>): void {
    this.criteria.update((c) => ({ ...c, page: 1, ...patch }));
  }

  clear(): void {
    this.criteria.set(NONE);
  }

  refresh(): void {
    this.found.reload();
  }
}

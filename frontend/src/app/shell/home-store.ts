import { Injectable, inject, signal } from '@angular/core';
import { Api } from '../api/api';
import { homeApiHomeGet } from '../api/functions';
import { Home } from '../api/models';

/** The sidebar and the Do zrobienia queue, from the one home endpoint. */
@Injectable({ providedIn: 'root' })
export class HomeStore {
  private readonly api = inject(Api);
  readonly home = signal<Home | null>(null);

  async refresh(): Promise<void> {
    this.home.set(await this.api.invoke(homeApiHomeGet));
  }
}

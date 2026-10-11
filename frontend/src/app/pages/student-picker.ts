import { Component, computed, inject, input, output, resource, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../api/api';
import { usersApiUsersGet } from '../api/functions';
import { Candidate } from '../api/models';

/** Searches the tenant's users by name and offers each to pick as a Student. */
@Component({
  selector: 'cl-student-picker',
  imports: [FormsModule],
  template: `
    <label class="search-label">
      Szukaj ucznia
      <input
        type="search"
        class="search"
        placeholder="Imię lub nazwisko"
        [ngModel]="query()"
        [ngModelOptions]="{ standalone: true }"
        (keydown.enter)="$event.preventDefault()"
        (ngModelChange)="query.set($event)"
      />
    </label>
    @if (results().length) {
      <ul aria-label="Wyniki wyszukiwania">
        @for (c of results(); track c.user_id) {
          <li>
            <span>
              {{ c.display_name }} <span class="muted">{{ c.upn }}</span>
            </span>
            <button
              type="button"
              class="btn ghost"
              [attr.aria-label]="'Dodaj: ' + c.display_name"
              (click)="picked.emit(c)"
            >
              Dodaj
            </button>
          </li>
        }
      </ul>
    } @else if (query().trim() && found.value()) {
      <p class="muted">Nikogo nie znaleziono.</p>
    }
  `,
  styles: `
    .search-label {
      display: grid;
      gap: 4px;
      font-size: 14px;
    }
    .search {
      font: inherit;
      font-size: 16px;
      width: 100%;
      padding: 8px 12px;
      border: 1.5px solid var(--edge);
      border-radius: 4px;
      background: var(--card);
      color: var(--ink);
    }
    ul {
      list-style: none;
      margin: 8px 0 0;
      padding: 0;
    }
    li {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 6px 0;
      border-bottom: 1px solid var(--line);
    }
  `,
})
export class StudentPicker {
  private readonly api = inject(Api);
  /** Ids of the users that are Students already, who are not offered again. */
  readonly skip = input<string[]>([]);
  readonly picked = output<Candidate>();

  protected readonly query = signal('');
  protected readonly found = resource<Candidate[], string>({
    params: () => this.query().trim(),
    loader: async ({ params }) => (params ? this.api.invoke(usersApiUsersGet, { q: params }) : []),
  });
  protected readonly results = computed(() =>
    (this.found.value() ?? []).filter((c) => !this.skip().includes(c.user_id)),
  );
}

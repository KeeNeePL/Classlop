import { HttpErrorResponse } from '@angular/common/http';
import { Component, effect, inject, resource, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../api/api';
import {
  saveThresholdsApiSettingsThresholdsPut,
  thresholdsApiSettingsThresholdsGet,
} from '../api/functions';
import { Panel } from '../ui/panel';

const GRADES = [
  'dopuszczający (2)',
  'dostateczny (3)',
  'dobry (4)',
  'bardzo dobry (5)',
  'celujący (6)',
];

/** Ustawienia: the Suggested grade thresholds, one set for every Class. */
@Component({
  imports: [FormsModule, Panel],
  template: `
    <h1>Ustawienia</h1>
    <cl-panel>
      <h2>Progi proponowanych ocen</h2>
      <p class="muted">
        Najniższy procent punktów dla każdej oceny. Poniżej pierwszego progu proponowana ocena to
        niedostateczny (1). Progi zmieniają od razu wszystkie proponowane oceny, które widzisz tylko
        ty.
      </p>
      <form (submit)="$event.preventDefault(); save()">
        @for (grade of grades; track $index) {
          <label>
            <span>{{ grade }}</span>
            <input
              type="number"
              min="1"
              max="100"
              [name]="'t' + $index"
              [ngModel]="percents()[$index]"
              (ngModelChange)="set($index, $event)"
            />
            %
          </label>
        }
        <div class="buttons">
          <button class="btn" type="submit" [disabled]="state() === 'saving'">Zapisz progi</button>
          @switch (state()) {
            @case ('saved') {
              <span class="muted" role="status">Zapisano.</span>
            }
            @case ('refused') {
              <span class="error" role="alert"
                >Każdy próg musi być wyższy od poprzedniego, a ostatni co najwyżej 100%.</span
              >
            }
            @case ('failed') {
              <span class="error" role="alert">Nie udało się zapisać progów.</span>
            }
          }
        </div>
      </form>
    </cl-panel>
  `,
  styles: `
    :host {
      display: grid;
      gap: 16px;
    }
    h2 {
      margin: 0 0 8px;
    }
    form {
      display: grid;
      gap: 8px;
      margin-top: 12px;
      justify-items: start;
    }
    label {
      display: grid;
      grid-template-columns: 180px 72px auto;
      gap: 8px;
      align-items: center;
    }
    input {
      font: inherit;
      text-align: right;
      padding: 2px 6px;
      border: 1px solid var(--line);
      border-radius: 4px;
    }
    .buttons {
      display: flex;
      gap: 12px;
      align-items: center;
      margin-top: 8px;
    }
    .error {
      color: var(--red);
      font-weight: 600;
    }
  `,
})
export class Settings {
  private readonly api = inject(Api);
  private readonly stored = resource({
    loader: () => this.api.invoke(thresholdsApiSettingsThresholdsGet, {}),
  });

  protected readonly grades = GRADES;
  protected readonly percents = signal<number[]>([]);
  protected readonly state = signal<'idle' | 'saving' | 'saved' | 'refused' | 'failed'>('idle');

  constructor() {
    effect(() => {
      const v = this.stored.hasValue() ? this.stored.value() : undefined;
      if (v) this.percents.set(v.percents);
    });
  }

  protected set(at: number, value: number) {
    this.percents.set(this.percents().map((p, i) => (i === at ? Number(value) : p)));
    this.state.set('idle');
  }

  protected async save() {
    this.state.set('saving');
    try {
      await this.api.invoke(saveThresholdsApiSettingsThresholdsPut, {
        body: { percents: this.percents() },
      });
      this.state.set('saved');
    } catch (e) {
      this.state.set(e instanceof HttpErrorResponse && e.status === 422 ? 'refused' : 'failed');
    }
  }
}

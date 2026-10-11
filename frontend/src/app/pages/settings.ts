import { HttpErrorResponse } from '@angular/common/http';
import { Component, effect, inject, resource, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api } from '../api/api';
import {
  latenessApiSettingsLatenessGet,
  saveThresholdsApiSettingsThresholdsPut,
  setLatenessApiSettingsLatenessPut,
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

/** Ustawienia: the Suggested grade thresholds and the lateness threshold, one set for every Class. */
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
    <cl-panel>
      <h2>Spóźnienie</h2>
      <p class="muted">
        Uczeń, który dołączył do lekcji później niż tyle minut po jej planowym początku, jest
        spóźniony. Jedno ustawienie dla wszystkich klas.
      </p>
      <form (submit)="$event.preventDefault(); saveLateness()">
        <label>
          <span>Próg spóźnienia</span>
          <input
            type="number"
            min="0"
            max="60"
            name="lateness"
            aria-label="Próg spóźnienia w minutach"
            [ngModel]="lateness()"
            (ngModelChange)="setLateness($event)"
          />
          min
        </label>
        <div class="buttons">
          <button class="btn" type="submit" [disabled]="latenessState() === 'saving'">
            Zapisz próg spóźnienia
          </button>
          @switch (latenessState()) {
            @case ('saved') {
              <span class="muted" role="status">Zapisano.</span>
            }
            @case ('failed') {
              <span class="error" role="alert">Podaj liczbę minut od 0 do 60.</span>
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
  private readonly storedLateness = resource({
    loader: () => this.api.invoke(latenessApiSettingsLatenessGet, {}),
  });

  protected readonly lateness = signal(5);
  protected readonly latenessState = signal<'idle' | 'saving' | 'saved' | 'failed'>('idle');

  constructor() {
    effect(() => {
      const v = this.stored.hasValue() ? this.stored.value() : undefined;
      if (v) this.percents.set(v.percents);
    });
    effect(() => {
      const v = this.storedLateness.hasValue() ? this.storedLateness.value() : undefined;
      if (v) this.lateness.set(v.minutes);
    });
  }

  protected setLateness(value: number) {
    this.lateness.set(Number(value));
    this.latenessState.set('idle');
  }

  protected async saveLateness() {
    this.latenessState.set('saving');
    try {
      await this.api.invoke(setLatenessApiSettingsLatenessPut, {
        body: { minutes: this.lateness() },
      });
      this.latenessState.set('saved');
    } catch {
      this.latenessState.set('failed');
    }
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

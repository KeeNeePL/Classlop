import { HttpErrorResponse } from '@angular/common/http';
import { Component, inject, resource, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { Api } from '../api/api';
import {
  addLessonApiClassesClassIdLessonsPost,
  lessonsApiClassesClassIdLessonsGet,
} from '../api/functions';
import { Badge } from '../ui/badge';
import { Panel } from '../ui/panel';
import { fromInput, warsaw } from '../time';

/** The Class page's Lekcje tab: the Lessons with their Lesson topic, and adding a single one. */
@Component({
  imports: [Badge, FormsModule, Panel, RouterLink],
  template: `
    @if (lessons.hasValue() && lessons.value(); as l) {
      <cl-panel>
        <h2>Lekcje</h2>
        <ul class="list" aria-label="Lekcje">
          @for (x of l.lessons; track x.id) {
            <li [class.cancelled]="x.cancelled">
              <time>{{ at(x.start) }}</time>
              <a [routerLink]="[x.id]">{{ x.topic ?? 'bez tematu' }}</a>
              <span>
                @if (x.cancelled) {
                  <cl-badge>odwołana</cl-badge>
                } @else if (x.missing_topic) {
                  <cl-badge tone="warn">brak tematu</cl-badge>
                }
              </span>
            </li>
          } @empty {
            <li class="muted">
              Ta klasa nie ma jeszcze lekcji. Dodaj plan lekcji albo pojedynczą lekcję.
            </li>
          }
        </ul>
      </cl-panel>

      @if (!l.read_only) {
        <cl-panel>
          <h2>Dodaj lekcję</h2>
          @if (error(); as e) {
            <p class="error" role="alert">{{ e }}</p>
          }
          <form class="add" (ngSubmit)="add()">
            <label>
              Temat lekcji
              <input
                class="text"
                name="topic"
                required
                [ngModel]="topic()"
                (ngModelChange)="topic.set($event)"
              />
            </label>
            <label>
              Początek
              <input
                class="text"
                type="datetime-local"
                name="start"
                required
                [ngModel]="start()"
                (ngModelChange)="start.set($event)"
              />
            </label>
            <label>
              Koniec
              <input
                class="text"
                type="datetime-local"
                name="end"
                required
                [ngModel]="end()"
                (ngModelChange)="end.set($event)"
              />
            </label>
            <button
              type="submit"
              class="btn"
              [disabled]="busy() || !topic().trim() || !start() || !end()"
            >
              Dodaj lekcję
            </button>
          </form>
        </cl-panel>
      }
    } @else if (lessons.error()) {
      <p class="error" role="alert">Nie udało się wczytać lekcji.</p>
    }
  `,
  styleUrl: './lessons.css',
})
export class Lessons {
  private readonly api = inject(Api);
  private readonly id = toSignal(
    inject(ActivatedRoute).parent!.paramMap.pipe(map((p) => p.get('klasa') ?? '')),
    { requireSync: true },
  );

  protected readonly lessons = resource({
    params: () => this.id(),
    loader: ({ params }) =>
      this.api.invoke(lessonsApiClassesClassIdLessonsGet, { class_id: params }),
  });
  protected readonly topic = signal('');
  protected readonly start = signal('');
  protected readonly end = signal('');
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly at = warsaw;

  protected async add(): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await this.api.invoke(addLessonApiClassesClassIdLessonsPost, {
        class_id: this.id(),
        body: {
          topic: this.topic().trim(),
          start: fromInput(this.start()),
          end: fromInput(this.end()),
        },
      });
      this.topic.set('');
      this.lessons.reload();
    } catch (e) {
      this.error.set(
        e instanceof HttpErrorResponse && e.status === 409
          ? 'Teams nie pozwala na tę zmianę. Odśwież stronę i sprawdź stan klasy.'
          : 'Nie udało się dodać lekcji. Sprawdź temat i godziny.',
      );
    } finally {
      this.busy.set(false);
    }
  }
}

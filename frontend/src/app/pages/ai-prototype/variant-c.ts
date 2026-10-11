// PROTOTYPE (throwaway). Variant C, "Tryby": the Teacher picks what to do (generate, upload, ask)
// and gets a small form for it instead of a blank text box; the conversation becomes a compact
// history under the form. Chats are a grouped list on the left.
import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Badge } from '../../ui/badge';
import { MathText } from '../../ui/math';
import { ProgressBar } from '../../ui/progress-bar';
import { Demo } from './demo';

type Mode = 'generate' | 'upload' | 'ask';

@Component({
  selector: 'cl-variant-c',
  imports: [Badge, FormsModule, MathText, ProgressBar],
  template: `
    <div class="grid">
      <aside class="rail" aria-label="Czaty">
        <button type="button" class="btn ghost" (click)="demo.open(null)">+ Nowy czat</button>
        <input
          type="search"
          aria-label="Szukaj czatów"
          placeholder="Szukaj czatów"
          [ngModel]="demo.query()"
          (ngModelChange)="demo.query.set($event)"
        />
        @for (group of groups; track group) {
          <h2>{{ group }}</h2>
          <ul>
            @for (c of inGroup(group); track c.id) {
              <li [class.on]="c.id === demo.chatId()">
                <button type="button" class="pick" (click)="demo.open(c.id)">{{ c.name }}</button>
                @if (demo.runningIn(c.id)) {
                  <cl-badge tone="live" aria-label="Trwające zadania">{{ demo.runningIn(c.id) }}</cl-badge>
                }
                <details class="more">
                  <summary aria-label="Więcej: {{ c.name }}">...</summary>
                  <div class="drop">
                    <button type="button" (click)="demo.rename(c.id, c.name + ' (zmienione)')">Zmień nazwę</button>
                    <button type="button" class="danger" (click)="demo.remove(c.id)">Usuń</button>
                  </div>
                </details>
              </li>
            }
          </ul>
        }
      </aside>

      <section class="work">
        <h2 class="title">{{ demo.chat()?.name ?? 'Nowy czat' }}</h2>
        <div class="modes" role="tablist" aria-label="Co chcesz zrobić">
          @for (m of modes; track m.key) {
            <button type="button" role="tab" [attr.aria-selected]="mode() === m.key" [class.on]="mode() === m.key" (click)="mode.set(m.key)">
              {{ m.label }}
            </button>
          }
        </div>

        <form class="form" (submit)="$event.preventDefault(); submit()">
          @switch (mode()) {
            @case ('generate') {
              <label>Temat<input name="t" [ngModel]="topic()" (ngModelChange)="topic.set($event)" placeholder="np. równania liniowe" /></label>
              <label>Liczba zadań<input name="n" type="number" min="1" max="20" [ngModel]="count()" (ngModelChange)="count.set($event)" /></label>
              <label>Trudność
                <select name="d" [ngModel]="level()" (ngModelChange)="level.set($event)">
                  <option>łatwe</option><option>średnie</option><option>trudne</option>
                </select>
              </label>
              <label>Format
                <select name="f" [ngModel]="kind()" (ngModelChange)="kind.set($event)">
                  <option>zamknięte</option><option>otwarte</option>
                </select>
              </label>
              <button type="submit" class="btn send">Generuj {{ count() }} zadań</button>
            }
            @case ('upload') {
              <label class="zone">
                @if (file()) {
                  Wybrany plik: <b>{{ file() }}</b>
                } @else {
                  Przeciągnij tu PDF albo zdjęcie albo kliknij, żeby wybrać
                }
                <input type="file" hidden (change)="attach($event)" />
              </label>
              <button type="submit" class="btn send" [disabled]="!file()">Wgraj zadania</button>
            }
            @case ('ask') {
              <label class="wide">Pytanie
                <textarea name="q" rows="3" [ngModel]="question()" (ngModelChange)="question.set($event)" placeholder="Napisz do Classlop AI"></textarea>
              </label>
              <button type="submit" class="btn send">Wyślij</button>
            }
          }
        </form>

        <h3>Przebieg</h3>
        <div class="feed" role="log" aria-label="Rozmowa" aria-live="polite">
          @for (m of demo.messages(); track m.id) {
            <article class="row" [class.me]="m.role === 'user'">
              <span class="who">{{ m.role === 'user' ? 'Ty' : 'AI' }}</span>
              <div>
                @if (m.file) {
                  <p class="file">Plik: <b>{{ m.file }}</b></p>
                }
                <cl-math [text]="m.text" />
                @if (m.job; as job) {
                  <section class="job" [attr.aria-label]="job.title">
                    <b>{{ job.title }}</b>
                    <div class="dots">
                      @for (s of job.steps; track $index) {
                        <span [class]="s.state" [title]="s.label"></span>
                      }
                    </div>
                    <span class="muted">{{ currentStep(job) }}</span>
                    @if (job.percent < 100) {
                      <cl-progress [value]="job.percent" />
                    }
                    @if (job.items.length) {
                      <table>
                        <caption class="sr">Dodane zadania</caption>
                        <thead><tr><th>Nr</th><th>Zadanie</th><th>Trudność</th><th></th></tr></thead>
                        <tbody>
                          @for (i of job.items; track i.number) {
                            <tr [class.gone]="i.retired">
                              <td>{{ i.number }}</td>
                              <td>
                                <cl-math [text]="i.text" />
                                @if (i.flagged) {
                                  <cl-badge tone="warn">do sprawdzenia</cl-badge>
                                }
                              </td>
                              <td>{{ i.difficulty }}, {{ i.points }} pkt</td>
                              <td>
                                @if (!i.retired) {
                                  <button type="button" class="small" (click)="demo.retire(i)">Usuń</button>
                                }
                              </td>
                            </tr>
                          }
                        </tbody>
                      </table>
                    }
                    @for (p of job.pending; track p.page) {
                      <p class="decide">
                        <cl-math [text]="p.text" /> Podobne do zadania w banku.
                        <button type="button" class="btn ghost" (click)="demo.decide(job, p.page)">Wgraj mimo to</button>
                        <button type="button" class="btn" (click)="demo.decide(job, p.page)">Pomiń</button>
                      </p>
                    }
                  </section>
                }
              </div>
            </article>
          } @empty {
            <p class="muted">Nic tu jeszcze nie ma. Wybierz, co chcesz zrobić, i uzupełnij formularz.</p>
          }
          @if (demo.thinking()) {
            <p class="muted" role="status">AI pisze...</p>
          }
        </div>
      </section>
    </div>
  `,
  styles: `
    .grid { display: grid; grid-template-columns: minmax(0, 260px) minmax(0, 1fr); gap: 24px; align-items: start; }
    .rail { display: grid; gap: 6px; align-content: start; }
    h2 { margin: 10px 0 0; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
    ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 2px; }
    li { display: flex; align-items: center; gap: 4px; padding: 4px 6px; border-radius: 4px; border-left: 3px solid transparent; }
    li.on { background: #eef2fd; border-left-color: var(--pen); }
    .pick { flex: 1; min-width: 0; text-align: left; font: inherit; background: none; border: 0; cursor: pointer; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .more { position: relative; }
    .more summary { cursor: pointer; color: var(--muted); padding: 0 6px; list-style: none; }
    .drop { position: absolute; right: 0; z-index: 5; display: grid; width: 140px; padding: 4px; border: 1.5px solid var(--edge); border-radius: 4px; background: var(--card); box-shadow: 0 6px 20px rgba(0,0,0,.15); }
    .drop button { font: inherit; text-align: left; padding: 6px 8px; background: none; border: 0; cursor: pointer; }
    .drop .danger { color: var(--red); }
    input[type='search'], .rail input, .form input, .form select, textarea { font: inherit; padding: 8px 10px; border: 1.5px solid var(--edge); border-radius: 4px; background: var(--card); color: var(--ink); width: 100%; box-sizing: border-box; }
    .title { margin: 0 0 10px; font-family: var(--display); font-size: 22px; text-transform: none; letter-spacing: 0; color: var(--ink); }
    .modes { display: flex; gap: 0; border-bottom: 1.5px solid var(--line); }
    .modes button { font: inherit; padding: 8px 18px; background: none; border: 0; border-bottom: 3px solid transparent; cursor: pointer; color: var(--muted); }
    .modes .on { color: var(--ink); font-weight: 600; border-bottom-color: var(--pen); }
    .form { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; align-items: end; padding: 16px; margin-top: 12px; border: 1.5px solid var(--edge); border-radius: 4px; background: var(--card); }
    .form label { display: grid; gap: 4px; font-size: 13px; color: var(--muted); }
    .form .wide, .form .zone { grid-column: 1 / -1; }
    .zone { place-items: center; padding: 28px; border: 2px dashed var(--edge); border-radius: 4px; cursor: pointer; color: var(--ink); }
    .send { background: var(--pen); border-color: var(--pen); color: #fff; justify-self: start; }
    .send:disabled { opacity: 0.5; }
    h3 { margin: 20px 0 8px; font-size: 14px; }
    .feed { display: grid; gap: 0; }
    .row { display: grid; grid-template-columns: 36px 1fr; gap: 8px; padding: 10px 0; border-top: 1px solid var(--line); }
    .who { font-size: 12px; font-weight: 700; color: var(--muted); }
    .row.me .who { color: var(--pen); }
    .muted { color: var(--muted); }
    .file { margin: 0; font-size: 13px; }
    .job { display: grid; gap: 6px; margin-top: 8px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 4px; background: var(--paper); }
    .dots { display: flex; gap: 6px; }
    .dots span { width: 28px; height: 6px; border-radius: 3px; background: var(--line); }
    .dots .done { background: #1d6b3c; }
    .dots .now { background: var(--pen); }
    table { border-collapse: collapse; width: 100%; font-size: 14px; }
    th { text-align: left; font-size: 12px; color: var(--muted); border-bottom: 1px solid var(--line); padding: 4px 6px; }
    td { padding: 6px; border-bottom: 1px solid var(--line); vertical-align: top; }
    tr.gone { opacity: 0.45; }
    .sr { position: absolute; left: -9999px; }
    .small { font: inherit; font-size: 12px; background: none; border: 0; color: var(--muted); cursor: pointer; }
    .decide { margin: 0; padding: 8px 10px; border: 1px solid #d8b800; border-radius: 4px; background: #fffbe0; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } .form { grid-template-columns: 1fr 1fr; } }
  `,
})
export class VariantC {
  protected readonly demo = new Demo();
  protected readonly groups = ['Dzisiaj', 'Wcześniej'] as const;
  protected readonly modes: { key: Mode; label: string }[] = [
    { key: 'generate', label: 'Generuj zadania' },
    { key: 'upload', label: 'Wgraj plik' },
    { key: 'ask', label: 'Zadaj pytanie' },
  ];
  protected readonly mode = signal<Mode>('generate');
  protected readonly topic = signal('');
  protected readonly count = signal(3);
  protected readonly level = signal('łatwe');
  protected readonly kind = signal('zamknięte');
  protected readonly question = signal('');
  protected readonly file = signal<string | null>(null);

  protected inGroup(group: string) {
    return this.demo.shown().filter((c) => c.when === group);
  }

  protected currentStep(job: { steps: { label: string; state: string }[] }): string {
    return (job.steps.find((s) => s.state === 'now') ?? job.steps[job.steps.length - 1]).label;
  }

  protected attach(event: Event): void {
    this.file.set((event.target as HTMLInputElement).files?.[0]?.name ?? null);
  }

  protected submit(): void {
    if (this.mode() === 'generate') {
      this.demo.send(
        `Wygeneruj ${this.count()} zadań ${this.kind()}, ${this.level()}, z tematu: ${this.topic() || 'dowolnego'}.`,
      );
    } else if (this.mode() === 'upload') {
      this.demo.send('Wgraj zadania z tego pliku.', this.file() ?? undefined);
      this.file.set(null);
    } else {
      this.demo.send(this.question());
      this.question.set('');
    }
  }
}

// PROTOTYPE (throwaway). Variant B, "Skupiony czat": one centred column like a modern assistant.
// Chats are tabs above it, a start screen offers the three things the Teacher does, job cards and
// Items sit inline in the conversation, and the composer is pinned to the bottom.
import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Badge } from '../../ui/badge';
import { MathText } from '../../ui/math';
import { ProgressBar } from '../../ui/progress-bar';
import { Demo } from './demo';

@Component({
  selector: 'cl-variant-b',
  imports: [Badge, FormsModule, MathText, ProgressBar],
  template: `
    <nav class="tabs" aria-label="Czaty">
      @for (c of demo.chats(); track c.id) {
        <button type="button" class="tab" [class.on]="c.id === demo.chatId()" (click)="demo.open(c.id)">
          {{ c.name }}
          @if (demo.runningIn(c.id)) {
            <cl-badge tone="live">{{ demo.runningIn(c.id) }}</cl-badge>
          }
        </button>
      }
      <button type="button" class="tab add" aria-label="Nowy czat" (click)="demo.open(null)">+</button>
      @if (demo.chat(); as chat) {
        <span class="grow"></span>
        <button type="button" class="small" (click)="renaming.set(!renaming())">Zmień nazwę</button>
        <button type="button" class="small" (click)="demo.remove(chat.id)">Usuń czat</button>
      }
    </nav>
    @if (renaming() && demo.chat(); as chat) {
      <input
        class="rename"
        aria-label="Nowa nazwa czatu"
        [value]="chat.name"
        (keydown.enter)="demo.rename(chat.id, $any($event.target).value); renaming.set(false)"
        (keydown.escape)="renaming.set(false)"
      />
    }

    <div class="column">
      <div class="log" role="log" aria-label="Rozmowa" aria-live="polite">
        @if (!demo.messages().length) {
          <div class="start">
            <h2>W czym pomóc?</h2>
            <div class="starters">
              <button type="button" (click)="text.set('Wygeneruj 5 zadań z ')">
                <b>Wygeneruj zadania</b>
                <span>Opisz własnymi słowami, jakich zadań potrzebujesz.</span>
              </button>
              <label>
                <b>Wgraj plik z zadaniami</b>
                <span>PDF albo zdjęcie. Zadania trafią do banku zadań.</span>
                <input type="file" hidden (change)="attach($event)" />
              </label>
              <button type="button" (click)="text.set('')">
                <b>Zadaj pytanie</b>
                <span>Na przykład o zadania w banku albo o podstawę programową.</span>
              </button>
            </div>
          </div>
        }
        @for (m of demo.messages(); track m.id) {
          @if (m.role === 'user') {
            <div class="me">
              @if (m.file) {
                <p class="file">Plik: <b>{{ m.file }}</b></p>
              }
              <cl-math [text]="m.text" />
            </div>
          } @else {
            <div class="ai">
              <span class="who">Classlop AI</span>
              <cl-math [text]="m.text" />
              @if (m.job; as job) {
                <section class="job" [attr.aria-label]="job.title">
                  <h3>{{ job.title }}</h3>
                  <ol class="steps">
                    @for (s of job.steps; track $index) {
                      <li [class]="s.state">{{ s.label }}</li>
                    }
                  </ol>
                  @if (job.percent < 100) {
                    <cl-progress [value]="job.percent" />
                  }
                  @for (p of job.pending; track p.page) {
                    <div class="decide">
                      <cl-math [text]="p.text" />
                      <span class="muted">Podobne do zadania w banku (strona {{ p.page }}).</span>
                      <button type="button" class="btn ghost" (click)="demo.decide(job, p.page)">Wgraj mimo to</button>
                      <button type="button" class="btn" (click)="demo.decide(job, p.page)">Pomiń</button>
                    </div>
                  }
                  @for (i of job.items; track i.number) {
                    <div class="item" [class.gone]="i.retired">
                      <span class="n">{{ i.number }}</span>
                      <div>
                        <cl-math [text]="i.text" />
                        <div class="meta">
                          <cl-badge>{{ i.difficulty }}</cl-badge>
                          <cl-badge>{{ i.points }} pkt</cl-badge>
                          @if (i.flagged) {
                            <cl-badge tone="warn">do sprawdzenia</cl-badge>
                          }
                          <details>
                            <summary>Rozwiązanie</summary>
                            <cl-math [text]="i.solution" />
                          </details>
                        </div>
                      </div>
                      @if (!i.retired) {
                        <button type="button" class="small" (click)="demo.retire(i)">Usuń</button>
                      }
                    </div>
                  }
                </section>
              }
            </div>
          }
        }
        @if (demo.thinking()) {
          <div class="ai muted" role="status">AI pisze...</div>
        }
      </div>

      <form class="composer" (submit)="$event.preventDefault(); send()">
        @if (file()) {
          <p class="file">Plik: <b>{{ file() }}</b> <button type="button" class="small" (click)="file.set(null)">Odłącz</button></p>
        }
        <div class="row">
          <label class="clip" title="Dołącz plik">Plik<input type="file" hidden (change)="attach($event)" /></label>
          <textarea rows="1" aria-label="Wiadomość" placeholder="Napisz do Classlop AI" [ngModel]="text()" (ngModelChange)="text.set($event)" name="m"></textarea>
          <button type="submit" class="btn send">Wyślij</button>
        </div>
      </form>
    </div>
  `,
  styles: `
    .tabs { display: flex; gap: 4px; align-items: center; overflow-x: auto; border-bottom: 1.5px solid var(--line); margin-bottom: 16px; }
    .tab { font: inherit; padding: 8px 14px; border: 0; border-bottom: 3px solid transparent; background: none; color: var(--muted); cursor: pointer; white-space: nowrap; display: flex; gap: 6px; align-items: center; }
    .tab.on { color: var(--ink); border-bottom-color: var(--pen); font-weight: 600; }
    .grow { flex: 1; }
    .small { font: inherit; font-size: 12px; background: none; border: 0; color: var(--muted); cursor: pointer; white-space: nowrap; }
    .rename { font: inherit; width: 320px; padding: 6px 10px; margin-bottom: 12px; border: 1.5px solid var(--pen); border-radius: 4px; }
    .column { max-width: 780px; margin: 0 auto; display: grid; gap: 16px; }
    .log { display: grid; gap: 22px; align-content: start; min-height: 440px; }
    .me { justify-self: end; max-width: 80%; padding: 10px 16px; border-radius: 18px 18px 4px 18px; background: #eef2fd; }
    .ai { display: grid; gap: 8px; }
    .who { font-size: 12px; font-weight: 700; color: var(--pen); text-transform: uppercase; letter-spacing: 0.04em; }
    .muted { color: var(--muted); }
    .start { text-align: center; padding-top: 40px; }
    .start h2 { font-family: var(--display); font-size: 28px; margin: 0 0 20px; }
    .starters { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
    .starters > * { display: grid; gap: 6px; padding: 16px; text-align: left; font: inherit; color: var(--ink); background: var(--card); border: 1.5px solid var(--edge); border-radius: 8px; cursor: pointer; }
    .starters span { color: var(--muted); font-size: 13px; }
    .job { display: grid; gap: 10px; padding: 14px 16px; border: 1.5px solid var(--edge); border-radius: 8px; background: var(--card); }
    h3 { margin: 0; font-size: 14px; }
    .steps { display: flex; gap: 4px 18px; flex-wrap: wrap; margin: 0; padding: 0; list-style: none; font-size: 13px; color: var(--muted); }
    .steps .done { color: #1d6b3c; }
    .steps .done::before { content: 'ok '; }
    .steps .now { color: var(--pen); font-weight: 600; }
    .item { display: grid; grid-template-columns: 28px 1fr auto; gap: 10px; align-items: start; padding: 10px 0; border-top: 1px solid var(--line); }
    .item.gone { opacity: 0.45; }
    .n { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 50%; background: var(--ink); color: #fff; font-weight: 700; font-size: 13px; }
    .meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 6px; }
    .decide { display: grid; gap: 6px; padding: 10px; border: 1px solid #d8b800; border-radius: 4px; background: #fffbe0; }
    .composer { position: sticky; bottom: 56px; display: grid; gap: 6px; padding: 10px; border: 1.5px solid var(--edge); border-radius: 12px; background: var(--card); box-shadow: 0 -6px 16px rgba(255,255,255,.9); }
    .row { display: flex; gap: 8px; align-items: end; }
    textarea { flex: 1; font: inherit; resize: none; padding: 8px; border: 0; outline: none; background: none; color: var(--ink); }
    .clip { cursor: pointer; padding: 6px 10px; border: 1.5px solid var(--edge); border-radius: 4px; font-size: 13px; }
    .send { background: var(--pen); border-color: var(--pen); color: #fff; }
    .file { margin: 0; font-size: 13px; }
    @media (max-width: 700px) { .starters { grid-template-columns: 1fr; } }
  `,
})
export class VariantB {
  protected readonly demo = new Demo();
  protected readonly text = signal('');
  protected readonly file = signal<string | null>(null);
  protected readonly renaming = signal(false);

  protected attach(event: Event): void {
    this.file.set((event.target as HTMLInputElement).files?.[0]?.name ?? null);
  }

  protected send(): void {
    this.demo.send(this.text(), this.file() ?? undefined);
    this.text.set('');
    this.file.set(null);
  }
}

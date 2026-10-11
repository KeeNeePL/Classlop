// PROTOTYPE (throwaway). Variant A, "Warsztat": the chat on the left, a side panel on the right
// that gathers what the chat produced (running jobs, decisions waiting, Items). The chat itself
// only carries one-line job chips. The Chat list folds into a menu above the chat.
import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Badge } from '../../ui/badge';
import { MathText } from '../../ui/math';
import { ProgressBar } from '../../ui/progress-bar';
import { Demo } from './demo';

@Component({
  selector: 'cl-variant-a',
  imports: [Badge, FormsModule, MathText, ProgressBar],
  template: `
    <div class="grid">
      <section class="main" aria-label="Rozmowa">
        <div class="bar">
          <details class="menu">
            <summary>
              {{ demo.chat()?.name ?? 'Nowy czat' }}
              @if (demo.running().length) {
                <cl-badge tone="live">{{ demo.running().length }} w toku</cl-badge>
              }
            </summary>
            <div class="pop">
              <input
                type="search"
                aria-label="Szukaj czatów"
                placeholder="Szukaj czatów"
                [ngModel]="demo.query()"
                (ngModelChange)="demo.query.set($event)"
              />
              <ul>
                @for (c of demo.shown(); track c.id) {
                  <li [class.on]="c.id === demo.chatId()">
                    <button type="button" class="pick" (click)="demo.open(c.id)">{{ c.name }}</button>
                    @if (demo.runningIn(c.id)) {
                      <cl-badge tone="live">{{ demo.runningIn(c.id) }}</cl-badge>
                    }
                    <button type="button" class="small" [attr.aria-label]="'Usuń czat: ' + c.name" (click)="demo.remove(c.id)">
                      Usuń
                    </button>
                  </li>
                }
              </ul>
              <button type="button" class="btn ghost" (click)="demo.open(null)">+ Nowy czat</button>
            </div>
          </details>
        </div>

        <div class="log" role="log" aria-label="Rozmowa" aria-live="polite">
          @if (!demo.messages().length) {
            <p class="muted">Napisz, jakich zadań potrzebujesz, albo dołącz plik z zadaniami.</p>
          }
          @for (m of demo.messages(); track m.id) {
            <div class="msg" [class.me]="m.role === 'user'">
              @if (m.file) {
                <p class="file">Plik: <b>{{ m.file }}</b></p>
              }
              <cl-math [text]="m.text" />
              @if (m.job; as job) {
                <div class="chip" [class.run]="job.percent < 100">
                  <b>{{ job.title }}</b>
                  <span>{{ job.percent < 100 ? 'w toku' : job.items.length + ' zadań gotowych' }}</span>
                  <cl-progress [value]="job.percent" />
                </div>
              }
            </div>
          }
          @if (demo.thinking()) {
            <div class="msg muted" role="status">AI pisze...</div>
          }
        </div>

        <form class="composer" (submit)="$event.preventDefault(); send()">
          <div class="quick">
            <button type="button" class="btn" (click)="text.set('Wygeneruj 3 zadania zamknięte z ')">Wygeneruj zadania</button>
            <label class="btn">Wgraj plik<input type="file" hidden (change)="attach($event)" /></label>
          </div>
          @if (file()) {
            <p class="file">Plik: <b>{{ file() }}</b></p>
          }
          <textarea rows="2" aria-label="Wiadomość" placeholder="Napisz do Classlop AI" [ngModel]="text()" (ngModelChange)="text.set($event)" name="m"></textarea>
          <button type="submit" class="btn send">Wyślij</button>
        </form>
      </section>

      <aside class="panel" aria-label="Wyniki rozmowy">
        @if (demo.running().length) {
          <h2>W toku</h2>
          @for (j of demo.running(); track j.id) {
            <div class="card">
              <b>{{ j.title }}</b>
              <ol class="steps">
                @for (s of j.steps; track $index) {
                  <li [class]="s.state">{{ s.label }}</li>
                }
              </ol>
              <cl-progress [value]="j.percent" />
            </div>
          }
        }
        @if (demo.pending().length) {
          <h2>Czeka na Twoją decyzję</h2>
          @for (p of demo.pending(); track p.page) {
            <div class="card warn">
              <p><cl-math [text]="p.text" /></p>
              <p class="muted">Podobne do zadania w banku. Strona {{ p.page }}.</p>
              <button type="button" class="btn ghost" (click)="demo.decide(p.job, p.page)">Wgraj mimo to</button>
              <button type="button" class="btn" (click)="demo.decide(p.job, p.page)">Pomiń</button>
            </div>
          }
        }
        <h2>Zadania z tego czatu <span class="muted">({{ demo.items().length }})</span></h2>
        @for (i of demo.items(); track i.number) {
          <div class="card" [class.gone]="i.retired">
            <div class="head">
              <b>Zadanie {{ i.number }}</b>
              <cl-badge>{{ i.difficulty }}</cl-badge>
              <cl-badge>{{ i.points }} pkt</cl-badge>
              @if (i.flagged) {
                <cl-badge tone="warn">do sprawdzenia</cl-badge>
              }
            </div>
            <cl-math [text]="i.text" />
            <details>
              <summary>Rozwiązanie</summary>
              <cl-math [text]="i.solution" />
            </details>
            @if (!i.retired) {
              <button type="button" class="small" (click)="demo.retire(i)">Usuń</button>
            }
          </div>
        } @empty {
          <p class="muted">Zadania pojawią się tutaj, gdy AI je napisze.</p>
        }
      </aside>
    </div>
  `,
  styles: `
    .grid { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 20px; align-items: start; }
    .main { display: grid; gap: 12px; }
    .bar { display: flex; }
    .menu { position: relative; }
    .menu > summary { cursor: pointer; font-weight: 600; font-size: 18px; display: flex; gap: 8px; align-items: center; padding: 4px 12px; border: 1.5px solid var(--edge); border-radius: 4px; background: var(--card); }
    .menu > summary::after { content: '\\25BE'; color: var(--muted); }
    .pop { position: absolute; z-index: 5; top: 36px; left: 0; width: 340px; display: grid; gap: 8px; padding: 12px; border: 1.5px solid var(--edge); border-radius: 4px; background: var(--card); box-shadow: 0 6px 20px rgba(0,0,0,.15); }
    input[type='search'], textarea { font: inherit; width: 100%; padding: 8px 12px; border: 1.5px solid var(--edge); border-radius: 4px; background: var(--card); color: var(--ink); }
    ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 4px; }
    li { display: flex; gap: 6px; align-items: center; padding: 2px 6px; border-radius: 4px; }
    li.on { background: #eef2fd; }
    .pick { flex: 1; text-align: left; font: inherit; background: none; border: 0; cursor: pointer; color: var(--ink); }
    .small { font: inherit; font-size: 12px; background: none; border: 0; color: var(--muted); cursor: pointer; }
    .log { display: grid; gap: 10px; align-content: start; min-height: 420px; }
    .msg { justify-self: start; max-width: 80%; padding: 10px 14px; border: 1.5px solid var(--line); border-radius: 4px; background: var(--card); }
    .msg.me { justify-self: end; border-color: var(--pen); background: #eef2fd; }
    .chip { display: grid; gap: 4px; margin-top: 8px; padding: 8px 10px; border: 1px dashed var(--edge); border-radius: 4px; font-size: 13px; }
    .chip.run { border-color: var(--pen); }
    .composer { display: grid; gap: 8px; }
    .quick { display: flex; gap: 8px; }
    .send { justify-self: end; background: var(--pen); border-color: var(--pen); color: #fff; }
    .file { margin: 0 0 4px; font-size: 13px; }
    .muted { color: var(--muted); }
    .panel { display: grid; gap: 10px; align-content: start; padding: 14px; border: 1.5px solid var(--line); border-radius: 4px; background: var(--grid); position: sticky; top: 16px; max-height: calc(100vh - 100px); overflow: auto; }
    h2 { margin: 6px 0 0; font-size: 14px; }
    .card { display: grid; gap: 6px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 4px; background: var(--card); }
    .card.warn { border-color: #d8b800; background: #fffbe0; }
    .card.gone { opacity: 0.5; }
    .head { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
    .steps { margin: 0; padding-left: 18px; font-size: 13px; color: var(--muted); }
    .steps .done { color: var(--ink); }
    .steps .now { color: var(--pen); font-weight: 600; }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } .panel { position: static; max-height: none; } }
  `,
})
export class VariantA {
  protected readonly demo = new Demo();
  protected readonly text = signal('');
  protected readonly file = signal<string | null>(null);

  protected attach(event: Event): void {
    this.file.set((event.target as HTMLInputElement).files?.[0]?.name ?? null);
  }

  protected send(): void {
    this.demo.send(this.text(), this.file() ?? undefined);
    this.text.set('');
    this.file.set(null);
  }
}

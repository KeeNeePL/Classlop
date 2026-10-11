import { KeyValuePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, inject, resource, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { map } from 'rxjs';
import { Api } from '../api/api';
import {
  formApiClassesClassIdNewWorkGet,
  giveApiClassesClassIdAssignmentsPost,
  pickApiClassesClassIdNewWorkPickPost,
  swapApiClassesClassIdNewWorkSwapPost,
} from '../api/functions';
import { GivenWork, Placed, Shortfall } from '../api/models';
import { fromInput } from '../time';
import { Badge } from '../ui/badge';
import { MathText } from '../ui/math';
import { Panel } from '../ui/panel';
import { DIFFICULTY } from './bank-store';

type Level = Placed['difficulty'];
type Type = 'homework' | 'quiz' | 'exam';

interface Row {
  section: string;
  easy: number;
  medium: number;
  hard: number;
}

const LEVELS: Level[] = ['easy', 'medium', 'hard'];

const TYPE: Record<Type, string> = {
  homework: 'Praca domowa',
  quiz: 'Kartkówka',
  exam: 'Sprawdzian',
};

/** Nowa praca: the Teacher says how many Items of which sections and Difficulty, looks over what
 * the bank gives, and gives the Assignment now or at a time. */
@Component({
  imports: [Badge, FormsModule, KeyValuePipe, MathText, Panel, RouterLink],
  templateUrl: './new-work.html',
  styleUrl: './new-work.css',
})
export class NewWork {
  private readonly api = inject(Api);
  private readonly id = toSignal(
    inject(ActivatedRoute).paramMap.pipe(map((p) => p.get('klasa') ?? '')),
    { requireSync: true },
  );

  private readonly loaded = resource({
    params: () => this.id(),
    loader: ({ params }) => this.api.invoke(formApiClassesClassIdNewWorkGet, { class_id: params }),
  });
  // The value of a resource in its error state throws, so a 404 reads as no form.
  protected readonly form = computed(() => (this.loaded.hasValue() ? this.loaded.value() : null));
  protected readonly missing = computed(() => this.loaded.error() !== undefined);

  protected readonly types = Object.entries(TYPE) as [Type, string][];
  protected readonly levels = LEVELS;
  protected readonly difficulty = DIFFICULTY;
  protected readonly back = computed(() => ['/klasy', this.id()]);

  protected readonly step = signal<'form' | 'preview' | 'given'>('form');
  protected readonly type = signal<Type>('homework');
  protected readonly typed = signal<string | null>(null);
  protected readonly rows = signal<Row[]>([]);
  protected readonly allowReuse = signal(false);
  protected readonly everyone = signal(true);
  protected readonly picked = signal<ReadonlySet<string>>(new Set());
  protected readonly reminder = signal(true);
  protected readonly due = signal('');
  protected readonly later = signal(false);
  protected readonly publishAt = signal('');

  protected readonly entries = signal<Placed[]>([]);
  protected readonly shortfalls = signal<Shortfall[]>([]);
  /** Items for which a swap found no other in the bank. */
  protected readonly stuck = signal<ReadonlySet<string>>(new Set());
  protected readonly given = signal<GivenWork | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);

  /** The Items the bank has per cell, with or without those the Class already got. */
  private readonly stock = computed(() => {
    const f = this.form();
    const counts = (this.allowReuse() ? f?.stock : f?.unused) ?? [];
    return new Map(counts.map((c) => [`${c.section}|${c.difficulty}`, c.count]));
  });
  private readonly names = computed(
    () => new Map((this.form()?.sections ?? []).map((s) => [s.id, `${roman(s.id)}. ${s.name}`])),
  );

  /** Sections not in the table yet. */
  protected readonly addable = computed(() => {
    const used = new Set(this.rows().map((r) => r.section));
    return (this.form()?.sections ?? []).filter((s) => !used.has(s.id));
  });
  protected readonly autoTitle = computed(
    () =>
      this.rows()
        .map((r) => this.label(r.section))
        .join(' i ') || 'Nowa praca',
  );
  protected readonly title = computed(() => this.typed() ?? this.autoTitle());
  protected readonly total = computed(() =>
    this.rows().reduce((n, r) => n + r.easy + r.medium + r.hard, 0),
  );
  protected readonly canPick = computed(
    () => this.total() > 0 && (this.everyone() || this.picked().size > 0),
  );
  protected readonly points = computed(() =>
    this.entries().reduce((n, e) => n + e.item.version.points, 0),
  );
  protected readonly canGive = computed(
    () =>
      this.entries().length > 0 &&
      this.title().trim() !== '' &&
      this.due() !== '' &&
      (!this.later() || this.publishAt() !== '') &&
      !this.busy(),
  );

  protected label(section: string): string {
    return this.names().get(section) ?? section;
  }

  protected inBank(row: Row, level: Level): number {
    return this.stock().get(`${row.section}|${level}`) ?? 0;
  }

  protected addRow(section: string): void {
    if (section) this.rows.update((r) => [...r, { section, easy: 0, medium: 0, hard: 0 }]);
  }

  protected removeRow(section: string): void {
    this.rows.update((r) => r.filter((x) => x.section !== section));
  }

  protected count(section: string, level: Level, value: number): void {
    const n = Math.max(0, Math.min(20, Math.floor(value || 0)));
    this.rows.update((rows) => rows.map((r) => (r.section === section ? { ...r, [level]: n } : r)));
  }

  protected toggle(student: string): void {
    const next = new Set(this.picked());
    if (!next.delete(student)) next.add(student);
    this.picked.set(next);
  }

  protected pickAll(on: boolean): void {
    this.picked.set(new Set(on ? (this.form()?.students ?? []).map((s) => s.id) : []));
  }

  protected async pick(): Promise<void> {
    const lines = this.rows().flatMap((r) =>
      LEVELS.filter((level) => r[level] > 0).map((level) => ({
        section: r.section,
        difficulty: level,
        count: r[level],
      })),
    );
    await this.run(async () => {
      const found = await this.api.invoke(pickApiClassesClassIdNewWorkPickPost, {
        class_id: this.id(),
        body: { lines, allow_reuse: this.allowReuse() },
      });
      this.entries.set(found.entries);
      this.shortfalls.set(found.shortfalls);
      this.stuck.set(new Set());
      this.step.set('preview');
    }, 'Nie udało się dobrać zadań. Spróbuj jeszcze raz.');
  }

  protected async swap(entry: Placed): Promise<void> {
    await this.run(async () => {
      const { item } = await this.api.invoke(swapApiClassesClassIdNewWorkSwapPost, {
        class_id: this.id(),
        body: {
          section: entry.section,
          difficulty: entry.difficulty,
          exclude: this.entries().map((e) => e.item.id),
          allow_reuse: this.allowReuse(),
        },
      });
      if (item) {
        this.entries.update((all) => all.map((e) => (e === entry ? { ...e, item } : e)));
      } else {
        this.stuck.update((s) => new Set(s).add(entry.item.id));
      }
    }, 'Nie udało się podmienić zadania. Spróbuj jeszcze raz.');
  }

  protected remove(entry: Placed): void {
    this.entries.update((all) => all.filter((e) => e !== entry));
  }

  /** "brakuje 2 z 3: I. Liczby rzeczywiste, łatwe". */
  protected lacking(s: Shortfall): string {
    return `${s.wanted - s.got} z ${s.wanted}: ${this.label(s.section)}, ${DIFFICULTY[s.difficulty]}`;
  }

  protected async give(): Promise<void> {
    await this.run(async () => {
      this.given.set(
        await this.api.invoke(giveApiClassesClassIdAssignmentsPost, {
          class_id: this.id(),
          body: {
            title: this.title().trim(),
            type: this.type(),
            item_ids: this.entries().map((e) => e.item.id),
            student_ids: this.everyone() ? null : [...this.picked()],
            reminder_on: this.reminder(),
            due_at: fromInput(this.due()),
            publish_at: this.later() ? fromInput(this.publishAt()) : null,
          },
        }),
      );
      this.step.set('given');
    }, 'Nie udało się wydać pracy. Spróbuj jeszcze raz.');
  }

  /** One call to the server; what it refuses with a reason is shown as it says. */
  private async run(call: () => Promise<void>, failure: string): Promise<void> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await call();
    } catch (e) {
      const detail = e instanceof HttpErrorResponse ? e.error?.detail : null;
      this.error.set(typeof detail === 'string' ? detail : failure);
    } finally {
      this.busy.set(false);
    }
  }
}

/** `lo2024:III` as `III`. */
const roman = (section: string): string => section.split(':')[1] ?? section;

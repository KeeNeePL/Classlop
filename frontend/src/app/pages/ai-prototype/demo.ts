// PROTOTYPE (throwaway): invented data and a fake AI, so the variants can be judged on looks.
import { computed, signal } from '@angular/core';

export interface DemoItem {
  number: number;
  text: string;
  difficulty: string;
  points: number;
  solution: string;
  flagged: boolean;
  retired: boolean;
}

export interface DemoStep {
  label: string;
  state: 'done' | 'now' | 'todo';
}

export interface DemoJob {
  id: string;
  title: string;
  steps: DemoStep[];
  percent: number;
  items: DemoItem[];
  pending: { text: string; page: number }[];
}

export interface DemoMessage {
  id: number;
  role: 'user' | 'ai';
  text: string;
  file?: string;
  job?: DemoJob;
}

export interface DemoChat {
  id: string;
  name: string;
  when: 'Dzisiaj' | 'Wcześniej';
}

const ITEMS: DemoItem[] = [
  {
    number: 1,
    text: 'Rozwiąż równanie $2x + 3 = 11$.',
    difficulty: 'łatwe',
    points: 1,
    solution: '$2x = 8$, więc $x = 4$.',
    flagged: false,
    retired: false,
  },
  {
    number: 2,
    text: 'Dla jakiego $m$ funkcja $f(x) = (m-2)x + 1$ jest rosnąca?',
    difficulty: 'łatwe',
    points: 1,
    solution: 'Funkcja rośnie, gdy $m - 2 > 0$, czyli $m > 2$.',
    flagged: true,
    retired: false,
  },
  {
    number: 3,
    text: 'Wskaż rozwiązanie równania $3(x - 1) = x + 5$.',
    difficulty: 'łatwe',
    points: 1,
    solution: '$3x - 3 = x + 5$, więc $x = 4$.',
    flagged: false,
    retired: false,
  },
];

const done = (label: string): DemoStep => ({ label, state: 'done' });

const FINISHED: DemoJob = {
  id: 'j1',
  title: 'Generowanie zadań',
  steps: [done('Plan'), done('Pisanie zadań (3 z 3)'), done('Sprawdzanie'), done('Gotowe')],
  percent: 100,
  items: ITEMS,
  pending: [],
};

const UPLOADING: DemoJob = {
  id: 'j2',
  title: 'Wgrywanie pliku',
  steps: [
    done('Odczyt strony'),
    { label: 'Wyciąganie zadań (4 z 7)', state: 'now' },
    { label: 'Gotowe', state: 'todo' },
  ],
  percent: 57,
  items: [],
  pending: [{ text: 'Rozwiąż równanie $2x + 3 = 11$.', page: 2 }],
};

export const CHATS: DemoChat[] = [
  { id: 'a', name: 'Równania liniowe, kartkówka', when: 'Dzisiaj' },
  { id: 'b', name: 'Zadania z pliku o funkcjach', when: 'Dzisiaj' },
  { id: 'c', name: 'Procenty dla klasy 1B', when: 'Wcześniej' },
  { id: 'd', name: 'Pytanie o podstawę programową', when: 'Wcześniej' },
];

const START: Record<string, DemoMessage[]> = {
  a: [
    { id: 1, role: 'user', text: 'Wygeneruj 3 łatwe zadania zamknięte z równań liniowych.' },
    { id: 2, role: 'ai', text: 'Zaczynam generować 3 zadania.', job: FINISHED },
    { id: 3, role: 'user', text: 'Dzięki. Zadanie 2 zależy od parametru, sprawdzę je.' },
    { id: 4, role: 'ai', text: 'Zaznaczyłem je do sprawdzenia. Możesz je usunąć albo zostawić w banku zadań.' },
  ],
  b: [
    { id: 1, role: 'user', text: 'Wgraj zadania z tego pliku.', file: 'kartkowka-funkcje.pdf' },
    { id: 2, role: 'ai', text: 'Czytam plik. Jedno zadanie jest podobne do zadania z banku.', job: UPLOADING },
  ],
  c: [{ id: 1, role: 'user', text: 'Potrzebuję zadań z procentów.' }],
  d: [],
};

/** The open workspace: the Chats, the open one's messages, and an AI that answers after a moment. */
export class Demo {
  readonly chats = signal<DemoChat[]>(CHATS);
  readonly chatId = signal<string | null>('a');
  readonly query = signal('');
  readonly thinking = signal(false);
  private readonly store = signal<Record<string, DemoMessage[]>>(START);
  private next = 100;

  readonly chat = computed(() => this.chats().find((c) => c.id === this.chatId()) ?? null);
  readonly messages = computed(() => this.store()[this.chatId() ?? ''] ?? []);
  readonly jobs = computed(() => this.messages().flatMap((m) => (m.job ? [m.job] : [])));
  readonly items = computed(() => this.jobs().flatMap((j) => j.items));
  readonly running = computed(() => this.jobs().filter((j) => j.percent < 100));
  readonly pending = computed(() =>
    this.jobs().flatMap((j) => j.pending.map((p) => ({ job: j, ...p }))),
  );
  readonly shown = computed(() => {
    const q = this.query().trim().toLowerCase();
    return this.chats().filter((c) => c.name.toLowerCase().includes(q));
  });

  runningIn(id: string): number {
    return (this.store()[id] ?? []).filter((m) => m.job && m.job.percent < 100).length;
  }

  open(id: string | null): void {
    this.chatId.set(id);
  }

  rename(id: string, name: string): void {
    this.chats.update((all) => all.map((c) => (c.id === id ? { ...c, name } : c)));
  }

  remove(id: string): void {
    this.chats.update((all) => all.filter((c) => c.id !== id));
    if (this.chatId() === id) this.chatId.set(null);
  }

  retire(item: DemoItem): void {
    this.patchJobs((j) => ({
      ...j,
      items: j.items.map((i) => (i.number === item.number ? { ...i, retired: true } : i)),
    }));
  }

  decide(job: DemoJob, page: number): void {
    this.patchJobs((j) =>
      j.id === job.id ? { ...j, pending: j.pending.filter((p) => p.page !== page) } : j,
    );
  }

  send(text: string, file?: string): void {
    text = text.trim();
    if (!text && !file) return;
    let id = this.chatId();
    if (!id) {
      const made = `n${this.next++}`;
      id = made;
      const name = (text || file || 'Nowy czat').slice(0, 40);
      this.chats.update((all) => [{ id: made, name, when: 'Dzisiaj' }, ...all]);
      this.chatId.set(made);
    }
    const chat = id;
    this.push(chat, { id: this.next++, role: 'user', text, file });
    this.thinking.set(true);
    const asked = /zadań|zadania|wygeneruj/i.test(text);
    setTimeout(() => {
      this.thinking.set(false);
      if (!asked && !file) {
        this.push(chat, {
          id: this.next++,
          role: 'ai',
          text: 'Ile zadań, jakiej trudności i w jakim formacie?',
        });
        return;
      }
      const job: DemoJob = {
        id: `j${this.next}`,
        title: file ? 'Wgrywanie pliku' : 'Generowanie zadań',
        steps: [
          { label: 'Plan', state: 'now' },
          { label: 'Pisanie zadań', state: 'todo' },
          { label: 'Sprawdzanie', state: 'todo' },
          { label: 'Gotowe', state: 'todo' },
        ],
        percent: 10,
        items: [],
        pending: [],
      };
      this.push(chat, {
        id: this.next++,
        role: 'ai',
        text: file ? 'Czytam plik.' : 'Zaczynam generować 3 zadania.',
        job,
      });
      this.advance(job.id);
    }, 700);
  }

  private advance(jobId: string): void {
    let stage = 0;
    const tick = setInterval(() => {
      stage++;
      this.patchJobs((j) => {
        if (j.id !== jobId) return j;
        const steps = j.steps.map(
          (s, i): DemoStep => ({
            label: s.label,
            state: i < stage ? 'done' : i === stage ? 'now' : 'todo',
          }),
        );
        const finished = stage >= 3;
        return {
          ...j,
          steps,
          percent: finished ? 100 : 10 + stage * 30,
          items: finished ? ITEMS.map((i) => ({ ...i })) : [],
        };
      });
      if (stage >= 3) clearInterval(tick);
    }, 1200);
  }

  private push(id: string, message: DemoMessage): void {
    this.store.update((s) => ({ ...s, [id]: [...(s[id] ?? []), message] }));
  }

  private patchJobs(fn: (job: DemoJob) => DemoJob): void {
    this.store.update((s) =>
      Object.fromEntries(
        Object.entries(s).map(([id, msgs]) => [
          id,
          msgs.map((m) => (m.job ? { ...m, job: fn(m.job) } : m)),
        ]),
      ),
    );
  }
}

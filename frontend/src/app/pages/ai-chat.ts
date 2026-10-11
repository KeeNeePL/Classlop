import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { map } from 'rxjs';
import { Api } from '../api/api';
import { jobsApiChatsChatIdJobsGet, messagesApiChatsChatIdMessagesGet } from '../api/functions';
import { ChatMessage, JobCard } from '../api/models';
import { EventStream } from '../shell/event-stream';
import { MathText } from '../ui/math';
import { Panel } from '../ui/panel';
import { ProgressBar } from '../ui/progress-bar';
import { jobActive, jobPercent, jobState, jobTitle } from './ai-progress';
import { AiResults } from './ai-results';
import { AiStore, Outgoing, Reply } from './ai-store';

/** What the Teacher just sent and what the AI has said so far, before the Chat is read again. */
interface Turn {
  text: string;
  file: string | null;
  replies: Reply[];
}

const ASKED = 'Nie udało się wysłać wiadomości. Spróbuj jeszcze raz.';

/** One Chat: its history, the replies of a turn as they stream in, a chip for each job it started,
 * the box to write in, and beside them the results panel. Without a Chat (`/ai`) it is the empty start of one,
 * made when the first message is sent. */
@Component({
  imports: [AiResults, FormsModule, MathText, Panel, ProgressBar],
  templateUrl: './ai-chat.html',
  styleUrl: './ai-chat.css',
})
export class AiChat {
  private readonly api = inject(Api);
  private readonly store = inject(AiStore);
  private readonly router = inject(Router);
  protected readonly id = toSignal(
    inject(ActivatedRoute).paramMap.pipe(map((p) => p.get('czat') ?? '')),
    { requireSync: true },
  );

  protected readonly messages = signal<ChatMessage[]>([]);
  protected readonly jobs = signal<JobCard[]>([]);
  protected readonly turn = signal<Turn | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly text = signal('');
  protected readonly file = signal<File | null>(null);
  protected readonly sending = signal(false);
  protected readonly title = jobTitle;
  protected readonly state = jobState;
  protected readonly percent = jobPercent;
  protected readonly active = jobActive;

  protected readonly jobOf = computed(() => {
    const byId = new Map(this.jobs().map((j) => [j.job_id, j]));
    return (reply: { payload: Record<string, unknown> }) =>
      byId.get(reply.payload['job_id'] as string);
  });

  constructor() {
    const stream = inject(EventStream);
    effect(() => {
      const id = this.id();
      untracked(() => {
        this.messages.set([]);
        this.jobs.set([]);
        this.error.set(null);
        void this.read(id);
      });
    });
    // A job moving on changes its card, and a finished upload says what came of it.
    for (const event of [stream.of('generation'), stream.of('upload')]) {
      effect(() => {
        if (event()) untracked(() => void this.read(this.id()));
      });
    }
    effect(() => {
      if (stream.reopened()) untracked(() => void this.read(this.id()));
    });
    // The first message of a Chat made on the start screen.
    const first = this.store.outbox();
    if (first && this.id()) {
      this.store.outbox.set(null);
      void this.run(this.id(), first);
    }
  }

  /** Reads the Chat's history and jobs again. While a turn streams, its replies stand for the
   * history, so the turn that has finished says so. */
  protected async read(id: string, finished = false): Promise<void> {
    if (!id) return;
    try {
      const [messages, jobs] = await Promise.all([
        this.api.invoke(messagesApiChatsChatIdMessagesGet, { chat_id: id }),
        this.api.invoke(jobsApiChatsChatIdJobsGet, { chat_id: id }),
      ]);
      if (id !== this.id()) return;
      if (finished || !this.turn()) this.messages.set(messages);
      if (finished) this.turn.set(null);
      this.jobs.set(jobs);
    } catch (error) {
      if (error instanceof HttpErrorResponse && error.status === 404) {
        await this.router.navigate(['/ai']);
      }
    }
  }

  protected attach(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.file.set(input.files?.[0] ?? null);
    input.value = '';
  }

  protected key(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void this.send();
    }
  }

  protected async send(): Promise<void> {
    const out: Outgoing = { text: this.text().trim(), file: this.file() };
    if (this.sending() || (!out.text && !out.file)) return;
    this.text.set('');
    this.file.set(null);
    this.error.set(null);
    const id = this.id();
    if (id) return this.run(id, out);
    this.sending.set(true);
    try {
      const chat = await this.store.create();
      this.store.outbox.set(out);
      await this.router.navigate(['/ai', chat.id]);
    } catch {
      this.error.set(ASKED);
      this.text.set(out.text);
      this.file.set(out.file);
    } finally {
      this.sending.set(false);
    }
  }

  private async run(id: string, out: Outgoing): Promise<void> {
    this.sending.set(true);
    const turn: Turn = { text: out.text, file: out.file?.name ?? null, replies: [] };
    this.turn.set(turn);
    try {
      for await (const reply of this.store.say(id, out.text, out.file)) {
        this.turn.update((t) => t && { ...t, replies: [...t.replies, reply] });
      }
    } catch {
      this.error.set(ASKED);
    }
    await this.read(id, true);
    this.turn.set(null);
    this.sending.set(false);
    this.store.reload();
  }
}

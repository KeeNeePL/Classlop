import { Injectable, effect, inject, resource, signal, untracked } from '@angular/core';
import { Api } from '../api/api';
import {
  chatsApiChatsGet,
  createApiChatsPost,
  deleteApiChatsChatIdDelete,
  renameApiChatsChatIdPatch,
} from '../api/functions';
import { ChatEntry } from '../api/models';
import { EventStream } from '../shell/event-stream';
import { SseParser } from '../shell/sse';

/** What the AI said in a turn, as the turn endpoint streams it. */
export interface Reply {
  text: string;
  payload: Record<string, unknown>;
}

/** A message of the Teacher's that waits for its Chat to be made. */
export interface Outgoing {
  text: string;
  file: File | null;
}

/** The Classlop AI tab's Chat list, kept while the Teacher moves between Chats. */
@Injectable({ providedIn: 'root' })
export class AiStore {
  private readonly api = inject(Api);
  private readonly list = resource({ loader: () => this.api.invoke(chatsApiChatsGet) });
  readonly chats = this.list.value;
  /** The first message of a new Chat, passed to the screen the Teacher is taken to. */
  readonly outbox = signal<Outgoing | null>(null);

  constructor() {
    const stream = inject(EventStream);
    // A job moving on changes the badges, and a job done may have named nothing yet.
    for (const event of [stream.of('generation'), stream.of('upload')]) {
      effect(() => {
        if (event()) untracked(() => this.list.reload());
      });
    }
    effect(() => {
      if (stream.reopened()) untracked(() => this.list.reload());
    });
  }

  reload(): void {
    this.list.reload();
  }

  async create(): Promise<ChatEntry> {
    const chat = await this.api.invoke(createApiChatsPost, {});
    this.list.reload();
    return chat;
  }

  async rename(id: string, name: string): Promise<void> {
    await this.api.invoke(renameApiChatsChatIdPatch, { chat_id: id, body: { name } });
    this.list.reload();
  }

  async remove(id: string): Promise<void> {
    await this.api.invoke(deleteApiChatsChatIdDelete, { chat_id: id });
    this.list.reload();
  }

  /** Sends one turn and yields the AI's replies as they are written; a turn the server could not
   * finish throws. The turn is a form posted once and read as it streams, which `HttpClient`
   * cannot do. */
  async *say(chatId: string, text: string, file: File | null): AsyncGenerator<Reply> {
    const form = new FormData();
    form.set('text', text);
    if (file) form.set('file', file);
    const response = await fetch(`/api/chats/${chatId}/messages`, { method: 'POST', body: form });
    if (!response.ok || !response.body) throw new Error(`the turn answered ${response.status}`);
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    const parser = new SseParser();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) throw new Error('the turn ended without a verdict');
      for (const frame of parser.push(value)) {
        if (frame.event === 'reply') yield JSON.parse(frame.data) as Reply;
        else if (frame.event === 'failed') throw new Error('the turn failed');
        else if (frame.event === 'done') return;
      }
    }
  }
}

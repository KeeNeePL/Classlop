import { Injectable, InjectionToken, Signal, computed, inject, signal } from '@angular/core';

/** What the server pushes about a job, by the kind of screen part it concerns. Mirrors
 * `Event` in backend/src/classlop/dashboard/events.py, which is left out of the OpenAPI
 * client since a stream has no generated call. */
export interface StreamEvent {
  kind: 'hand_in' | 'graded' | 'generation' | 'upload' | 'attendance';
  job_id: string;
  status: string;
  progress: Record<string, unknown> | null;
  at: string;
}

export const OPEN_STREAM = new InjectionToken<(url: string) => EventSource>('open stream', {
  factory: () => (url) => new EventSource(url),
});

const URL = '/api/events';
/** How long to wait before opening again once the browser has given up on the stream. */
const RECONNECT_MS = 3000;

/** The one event stream of this tab. The browser reopens a dropped stream by itself and sends
 * the last event id, so the server replays what was missed; only a stream the server refused
 * is left for this service to open again. */
@Injectable({ providedIn: 'root' })
export class EventStream {
  private readonly open = inject(OPEN_STREAM);
  private readonly latest = signal<Partial<Record<StreamEvent['kind'], StreamEvent>>>({});

  /** Counts the times the stream opened again; what was pushed in the gap is lost to it. */
  readonly reopened = signal(0);
  private opened = false;

  constructor() {
    this.connect();
  }

  /** The newest event of a kind, or undefined before any; a screen reacts to it changing. */
  of(kind: StreamEvent['kind']): Signal<StreamEvent | undefined> {
    return computed(() => this.latest()[kind]);
  }

  private connect(): void {
    const source = this.open(URL);
    source.onopen = () => {
      if (this.opened) this.reopened.update((n) => n + 1);
      this.opened = true;
    };
    source.onmessage = (message: MessageEvent<string>) => {
      const event: StreamEvent = JSON.parse(message.data);
      this.latest.update((all) => ({ ...all, [event.kind]: event }));
    };
    source.onerror = () => {
      if (source.readyState !== source.CLOSED) return;
      source.close();
      setTimeout(() => this.connect(), RECONNECT_MS);
    };
  }
}

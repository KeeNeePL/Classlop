import { TestBed } from '@angular/core/testing';
import { EventStream, OPEN_STREAM, StreamEvent } from './event-stream';

class FakeSource {
  CLOSED = 2;
  readyState = 1;
  onmessage: ((message: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  close = vi.fn(() => (this.readyState = this.CLOSED));

  push(event: Partial<StreamEvent>) {
    const full = { job_id: 'j', status: 'succeeded', progress: null, at: 'now', ...event };
    this.onmessage?.({ data: JSON.stringify(full) } as MessageEvent<string>);
  }
}

describe('EventStream', () => {
  const sources: FakeSource[] = [];

  beforeEach(() => {
    vi.useFakeTimers();
    sources.length = 0;
    TestBed.configureTestingModule({
      providers: [
        {
          provide: OPEN_STREAM,
          useValue: () => {
            const source = new FakeSource();
            sources.push(source);
            return source;
          },
        },
      ],
    });
  });

  afterEach(() => vi.useRealTimers());

  it('opens one stream and gives each kind its newest event', () => {
    const stream = TestBed.inject(EventStream);
    const graded = stream.of('graded');
    const attendance = stream.of('attendance');

    sources[0].push({ kind: 'graded', job_id: 'a' });
    sources[0].push({ kind: 'graded', job_id: 'b' });

    expect(sources).toHaveLength(1);
    expect(graded()?.job_id).toBe('b');
    expect(attendance()).toBeUndefined();
  });

  it('changes the signal of a kind only for events of that kind', () => {
    const stream = TestBed.inject(EventStream);
    const graded = stream.of('graded');
    sources[0].push({ kind: 'graded' });
    const before = graded();

    sources[0].push({ kind: 'hand_in' });

    expect(graded()).toBe(before);
  });

  it('counts each time the stream opens again, not the first open', () => {
    const stream = TestBed.inject(EventStream);

    sources[0].onopen?.();
    expect(stream.reopened()).toBe(0);
    sources[0].onopen?.();

    expect(stream.reopened()).toBe(1);
  });

  it('leaves a stream the browser is reopening alone', () => {
    TestBed.inject(EventStream);
    sources[0].readyState = 0;

    sources[0].onerror?.();
    vi.advanceTimersByTime(10_000);

    expect(sources).toHaveLength(1);
  });

  it('opens a new stream once the browser has given up on the old one', () => {
    TestBed.inject(EventStream);
    sources[0].readyState = sources[0].CLOSED;

    sources[0].onerror?.();
    expect(sources).toHaveLength(1);
    vi.advanceTimersByTime(3000);

    expect(sources).toHaveLength(2);
  });
});

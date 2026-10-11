import { SseParser } from './sse';

describe('SseParser', () => {
  it('cuts frames and waits for one split between chunks', () => {
    const parser = new SseParser();

    expect(parser.push('event: reply\ndata: {"text":"Ile')).toEqual([]);
    expect(parser.push(' zadań?"}\n\nevent: done\ndata: {}\n\n')).toEqual([
      { event: 'reply', data: '{"text":"Ile zadań?"}' },
      { event: 'done', data: '{}' },
    ]);
  });

  it('skips comments', () => {
    expect(new SseParser().push(': keepalive\n\n')).toEqual([]);
  });
});

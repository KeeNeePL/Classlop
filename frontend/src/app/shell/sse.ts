/** One server-sent event of a response read with `fetch`. */
export interface Frame {
  event: string;
  data: string;
}

/** Cuts a response body into frames as the chunks arrive; a frame split between two chunks waits
 * for the rest. */
export class SseParser {
  private rest = '';

  push(chunk: string): Frame[] {
    const blocks = (this.rest + chunk).split('\n\n');
    this.rest = blocks.pop() ?? '';
    return blocks.flatMap((block) => {
      const lines = block.split('\n');
      const field = (name: string) =>
        lines.find((l) => l.startsWith(name + ': '))?.slice(name.length + 2);
      const data = field('data');
      return data === undefined ? [] : [{ event: field('event') ?? 'message', data }];
    });
  }
}

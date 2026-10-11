const ZONE = 'Europe/Warsaw';

const moment = new Intl.DateTimeFormat('pl-PL', {
  timeZone: ZONE,
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
});

const day = new Intl.DateTimeFormat('pl-PL', {
  timeZone: ZONE,
  weekday: 'long',
  day: 'numeric',
  month: 'long',
});

/** An ISO 8601 UTC time as the Teacher reads it, in Warsaw. */
export const warsaw = (iso: string): string => moment.format(new Date(iso));

export const today = (): string => day.format(new Date());

const short = new Intl.DateTimeFormat('pl-PL', { timeZone: ZONE, day: 'numeric', month: 'short' });

export const shortDate = (at: string | number): string => short.format(new Date(at));

const fields = new Intl.DateTimeFormat('en-CA', {
  timeZone: ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** An ISO 8601 UTC time as a `datetime-local` value, in Warsaw whatever the browser's zone. */
export const toInput = (iso: string): string => {
  const p = Object.fromEntries(fields.formatToParts(new Date(iso)).map((f) => [f.type, f.value]));
  return `${p['year']}-${p['month']}-${p['day']}T${p['hour']}:${p['minute']}`;
};

/** A `datetime-local` value read as Warsaw time, back to ISO 8601 UTC. */
export const fromInput = (value: string): string => {
  const guess = Date.parse(`${value}Z`);
  const offset = Date.parse(`${toInput(new Date(guess).toISOString())}Z`) - guess;
  return new Date(guess - offset).toISOString();
};

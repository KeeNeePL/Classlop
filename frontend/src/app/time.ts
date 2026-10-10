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

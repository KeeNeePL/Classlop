import { JobCard } from '../api/models';
import { tasks } from '../labels';

export interface Step {
  label: string;
  state: 'done' | 'now' | 'todo' | 'failed';
}

type Counts = Record<string, number | undefined>;

const QUEUED = 'W kolejce';
const SIGN_IN = 'Czeka na zalogowanie do Teams';
const FAILED = 'Nie udało się';

export const jobTitle = (job: JobCard): string =>
  job.kind === 'upload' ? `Plik ${job.filename ?? ''}`.trim() : 'Generowanie zadań';

/** Queued, waiting for sign-in or running: neither done nor failed. */
export const jobActive = (job: JobCard): boolean =>
  job.status !== 'succeeded' && job.status !== 'failed';

/** How far the job is: what is done out of what there is, once the job knows. */
const counts = (job: JobCard) => {
  const p = (job.progress ?? {}) as Counts;
  return job.kind === 'upload'
    ? { done: p['pages_done'], total: p['pages'] }
    : { done: p['landed'], total: p['total'] };
};

/** 0 to 100, or nothing before the job knows its size. */
export const jobPercent = (job: JobCard): number | null => {
  const { done, total } = counts(job);
  return total ? Math.round(((done ?? 0) / total) * 100) : null;
};

export const jobSteps = (job: JobCard): Step[] => {
  const { kind, status } = job;
  const { done, total } = counts(job);
  const counted = total ? ` (${done ?? 0} z ${total})` : '';
  const waiting = status === 'queued' || status === 'waiting_for_sign_in';
  const working = status === 'failed' ? 'failed' : status === 'running' ? 'now' : 'done';
  return [
    { label: status === 'waiting_for_sign_in' ? SIGN_IN : QUEUED, state: waiting ? 'now' : 'done' },
    {
      label: (kind === 'upload' ? 'Odczyt stron' : 'Pisanie zadań') + counted,
      state: waiting ? 'todo' : working,
    },
    {
      label: status === 'failed' ? FAILED : 'Gotowe',
      state: status === 'succeeded' ? 'done' : status === 'failed' ? 'failed' : 'todo',
    },
  ];
};

/** The job's state in a few words, for its chip in the conversation. */
export const jobState = (job: JobCard): string =>
  ({
    succeeded: `Gotowe, ${tasks(job.items.length)}`,
    failed: `${FAILED}. Napisz prośbę jeszcze raz.`,
    waiting_for_sign_in: SIGN_IN,
    queued: QUEUED,
  })[job.status] ?? 'W toku';

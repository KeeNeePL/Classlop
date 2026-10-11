import { JobCard } from '../api/models';
import { tasks } from '../labels';

export interface Step {
  label: string;
  state: 'done' | 'now' | 'todo' | 'failed';
}

type Counts = Record<string, number | undefined>;

const WAITING = ['queued', 'waiting_for_sign_in'];

export const jobTitle = (job: JobCard): string =>
  job.kind === 'upload' ? `Plik ${job.filename ?? ''}`.trim() : 'Generowanie zadań';

export const jobFinished = (job: JobCard): boolean => job.status === 'succeeded';

/** How far the job is: what is done out of what there is, once the job knows. */
const counts = (job: JobCard) => {
  const p = (job.progress ?? {}) as Counts;
  return job.kind === 'upload'
    ? { done: p['pages_done'], total: p['pages'] }
    : { done: p['landed'], total: p['total'] };
};

/** 0 to 100 while the job works and knows its size, otherwise nothing. */
export const jobPercent = (job: JobCard): number | null => {
  const { done, total } = counts(job);
  return job.status === 'running' && total ? Math.round(((done ?? 0) / total) * 100) : null;
};

export const jobSteps = (job: JobCard): Step[] => {
  const { kind, status } = job;
  const { done, total } = counts(job);
  const counted = total ? ` (${done ?? 0} z ${total})` : '';
  const waiting = WAITING.includes(status);
  const working = status === 'failed' ? 'failed' : status === 'running' ? 'now' : 'done';
  return [
    {
      label: status === 'waiting_for_sign_in' ? 'Czeka na zalogowanie do Teams' : 'W kolejce',
      state: waiting ? 'now' : 'done',
    },
    {
      label: (kind === 'upload' ? 'Odczyt stron' : 'Pisanie zadań') + counted,
      state: waiting ? 'todo' : working,
    },
    {
      label: status === 'failed' ? 'Nie udało się' : 'Gotowe',
      state: status === 'succeeded' ? 'done' : status === 'failed' ? 'failed' : 'todo',
    },
  ];
};

/** The job's state in a few words, for its chip in the conversation. */
export const jobState = (job: JobCard): string => {
  switch (job.status) {
    case 'succeeded':
      return `gotowe, ${tasks(job.items.length)}`;
    case 'failed':
      return 'nie udało się';
    case 'waiting_for_sign_in':
      return 'czeka na zalogowanie do Teams';
    case 'queued':
      return 'w kolejce';
    default:
      return 'w toku';
  }
};

import { AssignmentPage, SummaryRow } from './api/models';

type Type = AssignmentPage['type'];
type State = SummaryRow['state'];

/** The Polish names the screens share. */
export const KIND: Record<Type, string> = {
  quiz: 'Kartkówka',
  exam: 'Sprawdzian',
  homework: 'Praca domowa',
};

export const KINDS: Record<Type, string> = {
  quiz: 'Kartkówki',
  exam: 'Sprawdziany',
  homework: 'Prace domowe',
};

const STATE: Record<State, string> = {
  not_handed_in: 'nie oddano',
  handed_in: 'oddano, ocenia AI',
  graded: 'ocenione',
  returned: 'zwrócone',
  missing: 'brak pracy',
  excused: 'zwolniony',
};

export const HELD = 'czeka na sprawdzenie';

/** A Submission's state as the Teacher reads it; a Held one waits for them whatever its state. */
export const stateLabel = (state: State, held: boolean) => (held ? HELD : STATE[state]);

/** "1 zadanie", "3 zadania", "5 zadań". */
export const tasks = (n: number): string => {
  const few = n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14);
  return `${n} ${n === 1 ? 'zadanie' : few ? 'zadania' : 'zadań'}`;
};

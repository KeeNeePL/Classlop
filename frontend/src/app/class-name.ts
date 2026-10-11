/** A Class as the Teacher calls it: "2A" is "Klasa 2A", and a name that already says so stays. */
export const classTitle = (name: string): string =>
  /^klasa\b/i.test(name) ? name : `Klasa ${name}`;

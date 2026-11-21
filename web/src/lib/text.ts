// Small wording helpers, kept pure so `npm test` checks them.

// A title used inside a sentence: "Told when Jeron is off" reads "told when Jeron is
// off". Only the first letter is lowered, and not at all when the first word is an
// acronym ("API token", "NSE history") or a name the rest of the title shares.
export function inSentence(title: string): string {
  const first = title.split(/\s/, 1)[0] ?? "";
  if (first.length > 1 && first === first.toUpperCase()) return title;
  if (/^Jeron\b/.test(title)) return title;
  return title.charAt(0).toLowerCase() + title.slice(1);
}

// "a, b and c": the titles of a list, joined for a sentence.
export function listInSentence(titles: string[]): string {
  const words = titles.map(inSentence);
  if (words.length < 2) return words.join("");
  return `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;
}

// Note numbers and recent events of the supplier card (tearsheet card, #163). Pure functions, no React.
// Numbers are given per source, in the order the sources first appear on the page, so the same source
// keeps the same number everywhere; a fact with no quote has no note.
import type { Fact } from "./api";
import { hostOf } from "./safeUrl";

/** What identifies a source across facts: its id, else its address. Null when the fact has no quote. */
export function sourceKey(fact: Fact): string | null {
  if (!fact.quote || fact.status === "not_found") return null;
  return fact.source_id ?? fact.source_url ?? `fact:${fact.id}`;
}

export type SourceEntry = {
  number: number;
  key: string;
  /** Title: the publisher, else the host of the address, else the address. */
  title: string;
  url: string | null;
  type: Fact["source_type"];
  fetchedAt: string | null;
  quotes: string[];
};

export type NoteIndex = {
  numberOf: (fact: Fact) => number | null;
  sources: SourceEntry[];
};

/** Numbers the sources of the facts in the order given (first appearance), and lists each source once. */
export function buildNoteIndex(ordered: readonly (Fact | null | undefined)[]): NoteIndex {
  const entries = new Map<string, SourceEntry>();
  for (const fact of ordered) {
    if (!fact) continue;
    const key = sourceKey(fact);
    if (!key) continue;
    let entry = entries.get(key);
    if (!entry) {
      entry = {
        number: entries.size + 1,
        key,
        title: fact.publisher ?? hostOf(fact.source_url) ?? fact.source_url ?? "",
        url: fact.source_url,
        type: fact.source_type,
        fetchedAt: fact.fetched_at,
        quotes: [],
      };
      entries.set(key, entry);
    }
    if (fact.quote && !entry.quotes.includes(fact.quote)) entry.quotes.push(fact.quote);
  }
  return {
    numberOf: (fact) => {
      const key = sourceKey(fact);
      return key ? (entries.get(key)?.number ?? null) : null;
    },
    sources: [...entries.values()],
  };
}

const MONTHS: Record<string, number> = {
  january: 1,
  jan: 1,
  janvier: 1,
  janv: 1,
  february: 2,
  feb: 2,
  fevrier: 2,
  fevr: 2,
  fev: 2,
  march: 3,
  mar: 3,
  mars: 3,
  april: 4,
  apr: 4,
  avril: 4,
  avr: 4,
  may: 5,
  mai: 5,
  june: 6,
  jun: 6,
  juin: 6,
  july: 7,
  jul: 7,
  juillet: 7,
  juil: 7,
  august: 8,
  aug: 8,
  aout: 8,
  september: 9,
  sep: 9,
  sept: 9,
  septembre: 9,
  october: 10,
  oct: 10,
  octobre: 10,
  november: 11,
  nov: 11,
  novembre: 11,
  december: 12,
  dec: 12,
  decembre: 12,
};

const monthNumber = (word: string): number | null =>
  MONTHS[word.normalize("NFD").replace(/[̀-ͯ.]/g, "").toLowerCase()] ?? null;

export type EventDate =
  | { precision: "day"; year: number; month: number; day: number }
  | { precision: "month"; year: number; month: number }
  | { precision: "year"; year: number };

const validDay = (year: number, month: number, day: number): boolean => {
  const date = new Date(Date.UTC(year, month - 1, day));
  return (
    date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
  );
};
const validYear = (year: number): boolean => year >= 1900 && year <= 2100;
const WORD = "[A-Za-z\\u00c0-\\u00ff]{3,9}\\.?";

/**
 * The date a value states, only when it is a full date, a month and a year, or a four-digit year; null
 * otherwise. The most precise form wins; the first match of that form is read.
 */
export function readEventDate(text: string): EventDate | null {
  const day = (year: number, month: number, d: number): EventDate | null =>
    validYear(year) && validDay(year, month, d) ? { precision: "day", year, month, day: d } : null;

  // Full date: 2021-02-23, 23/02/2021 (day first), Feb 23, 2021, 23 February 2021.
  for (const m of text.matchAll(/\b(\d{4})-(\d{2})-(\d{2})\b/g)) {
    const found = day(Number(m[1]), Number(m[2]), Number(m[3]));
    if (found) return found;
  }
  for (const m of text.matchAll(/\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b/g)) {
    const found = day(Number(m[3]), Number(m[2]), Number(m[1]));
    if (found) return found;
  }
  for (const m of text.matchAll(
    new RegExp(`\\b(${WORD})\\s+(\\d{1,2})(?:st|nd|rd|th)?,?\\s+(\\d{4})\\b`, "g"),
  )) {
    const month = monthNumber(m[1] ?? "");
    const found = month ? day(Number(m[3]), month, Number(m[2])) : null;
    if (found) return found;
  }
  for (const m of text.matchAll(
    new RegExp(`\\b(\\d{1,2})(?:er|st|nd|rd|th)?\\s+(?:of\\s+)?(${WORD})\\s+(\\d{4})\\b`, "g"),
  )) {
    const month = monthNumber(m[2] ?? "");
    const found = month ? day(Number(m[3]), month, Number(m[1])) : null;
    if (found) return found;
  }
  // Month and year: February 2021, février 2021, 02/2021.
  for (const m of text.matchAll(new RegExp(`\\b(${WORD})\\s+(\\d{4})\\b`, "g"))) {
    const month = monthNumber(m[1] ?? "");
    const year = Number(m[2]);
    if (month && validYear(year)) return { precision: "month", year, month };
  }
  for (const m of text.matchAll(/\b(\d{1,2})\/(\d{4})\b/g)) {
    const [month, year] = [Number(m[1]), Number(m[2])];
    if (month >= 1 && month <= 12 && validYear(year)) return { precision: "month", year, month };
  }
  // A four-digit year.
  for (const m of text.matchAll(/\b(\d{4})\b/g)) {
    if (validYear(Number(m[1]))) return { precision: "year", year: Number(m[1]) };
  }
  return null;
}

/** A sortable number for a date: its first day. */
export const eventTime = (date: EventDate): number =>
  Date.UTC(date.year, "month" in date ? date.month - 1 : 0, "day" in date ? date.day : 1);

export type TimelineEntry<T> = { item: T; date: EventDate | null };

/** Newest dated first (ties keep their order), undated last in their original order. */
export function sortTimeline<T>(entries: readonly TimelineEntry<T>[]): TimelineEntry<T>[] {
  const dated = entries.filter((entry) => entry.date);
  const undated = entries.filter((entry) => !entry.date);
  dated.sort((a, b) => eventTime(b.date as EventDate) - eventTime(a.date as EventDate));
  return [...dated, ...undated];
}

/** A date as the interface shows it: "Feb 23, 2021", "February 2021" or "2021". */
export function formatEventDate(date: EventDate, language: string): string {
  const locale = language === "fr" ? "fr-FR" : "en-US";
  if (date.precision === "year") return String(date.year);
  const moment = new Date(
    Date.UTC(date.year, date.month - 1, date.precision === "day" ? date.day : 1),
  );
  const options: Intl.DateTimeFormatOptions =
    date.precision === "month"
      ? { month: "long", year: "numeric", timeZone: "UTC" }
      : language === "fr"
        ? { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" }
        : { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" };
  return new Intl.DateTimeFormat(locale, options).format(moment);
}

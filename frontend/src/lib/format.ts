// Dates and numbers for the active locale: 25/10/2026 in French, Oct 25, 2026 in English.
const LOCALES: Record<string, string> = { en: "en-US", fr: "fr-FR" };
const locale = (language: string): string => LOCALES[language] ?? "en-US";

export function formatDate(value: string | Date, language: string): string {
  const date = typeof value === "string" ? new Date(value) : value;
  const options: Intl.DateTimeFormatOptions =
    language === "fr"
      ? { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "UTC" }
      : { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" };
  return new Intl.DateTimeFormat(locale(language), options).format(date);
}

/** Date and time in UTC, e.g. "Nov 4, 2026, 18:00 UTC" or "04/11/2026 18:00 UTC". */
export function formatDateTime(value: string | Date, language: string): string {
  const date = typeof value === "string" ? new Date(value) : value;
  const time = new Intl.DateTimeFormat(locale(language), {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: "UTC",
  }).format(date);
  const separator = language === "fr" ? " " : ", ";
  return `${formatDate(date, language)}${separator}${time} UTC`;
}

export function formatNumber(value: number, language: string): string {
  return new Intl.NumberFormat(locale(language)).format(value);
}

/**
 * The full country name for an ISO 3166-1 alpha-2 code in the interface language ("Germany",
 * "Allemagne"), from the browser's built-in `Intl.DisplayNames`. An unknown code, or a value that
 * is not a code, is shown as it is.
 */
export function countryName(code: string, language: string): string {
  if (!/^[A-Za-z]{2}$/.test(code)) return code;
  const upper = code.toUpperCase();
  try {
    const name = new Intl.DisplayNames([locale(language)], { type: "region" }).of(upper);
    return name && name !== upper ? name : upper;
  } catch {
    return upper;
  }
}

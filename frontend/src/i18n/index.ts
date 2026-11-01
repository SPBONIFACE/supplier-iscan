import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import fr from "./locales/fr.json";

export const LANGUAGES = ["en", "fr"] as const;
export type Language = (typeof LANGUAGES)[number];

// The choice is kept in this browser only (owner decision, 27 Oct 2026), never on the account.
export const LANGUAGE_STORAGE_KEY = "isc.language";

const isLanguage = (value: unknown): value is Language =>
  typeof value === "string" && (LANGUAGES as readonly string[]).includes(value);

/** The stored choice, else the browser language, else English. */
export function initialLanguage(): Language {
  try {
    const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (isLanguage(stored)) return stored;
  } catch {
    // Storage blocked: fall through to the browser language.
  }
  for (const tag of navigator.languages ?? [navigator.language]) {
    const base = tag.toLowerCase().split("-")[0];
    if (isLanguage(base)) return base;
  }
  return "en";
}

/** Switches the whole UI without a reload and remembers the choice in this browser. */
export async function setLanguage(language: Language): Promise<void> {
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Storage blocked: the language still changes for this visit.
  }
  await i18n.changeLanguage(language);
}

i18n.on("languageChanged", (language) => {
  document.documentElement.lang = language;
});

export async function initI18n(language: Language = initialLanguage()): Promise<typeof i18n> {
  if (!i18n.isInitialized) {
    await i18n.use(initReactI18next).init({
      resources: { en: { translation: en }, fr: { translation: fr } },
      lng: language,
      fallbackLng: "en",
      supportedLngs: [...LANGUAGES],
      interpolation: { escapeValue: false },
      returnNull: false,
    });
  } else {
    await i18n.changeLanguage(language);
  }
  document.documentElement.lang = language;
  return i18n;
}

export default i18n;

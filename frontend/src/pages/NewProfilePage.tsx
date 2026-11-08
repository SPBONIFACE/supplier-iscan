import { type FormEvent, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";
import { Button, FormField, LoadingIndicator } from "../components/ui";
import { api, type Language } from "../lib/api";
import { useTitle } from "../lib/useTitle";

// Countries offered as a hint (ISO 3166-1 alpha-2); names come from the browser in the UI language.
const COUNTRIES = [
  "AT",
  "BE",
  "BG",
  "CH",
  "CN",
  "CZ",
  "DE",
  "DK",
  "ES",
  "FI",
  "FR",
  "GB",
  "GR",
  "HU",
  "IE",
  "IN",
  "IT",
  "JP",
  "KR",
  "LU",
  "NL",
  "NO",
  "PL",
  "PT",
  "RO",
  "SE",
  "TR",
  "US",
] as const;

const INVISIBLE = /[​-‍⁠﻿\s]/g;
const asLanguage = (value: string): Language => (value.startsWith("fr") ? "fr" : "en");
const NAMES: Record<Language, string> = { en: "English", fr: "Français" };

type Errors = { name?: string; website?: string };

export function NewProfilePage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const uiLanguage = asLanguage(i18n.language);
  useTitle(t("titles.newProfile"));

  // The profile language starts as the UI language and follows it until the member chooses (owner decision, 27 Oct 2026).
  const [chosen, setChosen] = useState<Language | null>(null);
  const profileLanguage = chosen ?? uiLanguage;

  const [disclosure, setDisclosure] = useState<string | null>(null);
  const [disclosureFailed, setDisclosureFailed] = useState(false);
  const loadDisclosure = useCallback(async (language: Language) => {
    setDisclosureFailed(false);
    setDisclosure(null);
    const result = await api.getDisclosure(language);
    if (result.ok) setDisclosure(result.data.text);
    else setDisclosureFailed(true);
  }, []);
  useEffect(() => {
    void loadDisclosure(uiLanguage);
  }, [loadDisclosure, uiLanguage]);

  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [country, setCountry] = useState("");
  const [sector, setSector] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [unavailable, setUnavailable] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const websiteRef = useRef<HTMLInputElement>(null);
  const summaryRef = useRef<HTMLDivElement>(null);
  const countryId = useId();

  const countries = useMemo(() => {
    const names = new Intl.DisplayNames([uiLanguage], { type: "region" });
    return COUNTRIES.map((code) => ({ code, label: names.of(code) ?? code })).sort((a, b) =>
      a.label.localeCompare(b.label, uiLanguage),
    );
  }, [uiLanguage]);

  const prefixed = (message: string) => `${t("common.errorPrefix")} ${message}`;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    setUnavailable(false);
    // An empty or invisible-only name is flagged inline and no request is sent.
    if (!name.replace(INVISIBLE, "")) {
      setErrors({ name: t("newProfile.nameRequired") });
      nameRef.current?.focus();
      return;
    }
    setErrors({});
    setSubmitting(true);
    const result = await api.createIdentitySession({
      name: name.trim(),
      hints: {
        website: website.trim() || null,
        country: country || null,
        sector: sector.trim() || null,
      },
      profile_language: profileLanguage,
      ui_language: uiLanguage,
    });
    setSubmitting(false);
    if (result.ok) {
      navigate(`/profiles/new/${result.data.id}`, { state: { session: result.data } });
      return;
    }
    if (result.kind === "validation") {
      const found: Errors = {};
      for (const error of result.errors) {
        if (error.field.endsWith("website")) found.website = prefixed(error.message);
        else if (error.field.endsWith("name")) found.name = prefixed(error.message);
      }
      if (found.name || found.website) {
        setErrors(found);
        (found.name ? nameRef : websiteRef).current?.focus();
        return;
      }
    }
    if (result.kind !== "unauthorized") {
      setUnavailable(true);
      summaryRef.current?.focus();
    }
  }

  const errorCount = Object.values(errors).filter(Boolean).length;

  return (
    <section>
      <nav className="crumb" aria-label={t("newProfile.breadcrumb")}>
        <ol>
          <li>
            <Link to="/workspace">{t("nav.profiles")}</Link>
          </li>
          <li aria-current="page">{t("titles.newProfile")}</li>
        </ol>
      </nav>
      <h1>{t("titles.newProfile")}</h1>
      <div className="chat">
        <ol className="ts" aria-label={t("chat.log")}>
          <li className="turn turn-ai">
            <div className="turn-h">
              <span className="ml">{t("chat.assistant")}</span>
            </div>
            {disclosure ? <p className="disclosure">{disclosure}</p> : null}
            {!disclosure && !disclosureFailed ? <LoadingIndicator /> : null}
          </li>
        </ol>
        {disclosureFailed ? (
          <div role="alert" className="msg">
            <p>{prefixed(t("chat.disclosureFailed"))}</p>
            <div className="actions">
              <Button variant="secondary" onClick={() => void loadDisclosure(uiLanguage)}>
                {t("common.retry")}
              </Button>
            </div>
          </div>
        ) : null}
        {disclosure ? (
          <form
            className="form composer"
            noValidate
            onSubmit={onSubmit}
            aria-labelledby="request-title"
          >
            <h2 id="request-title" className="vh">
              {t("newProfile.request")}
            </h2>
            {unavailable ? (
              <div className="msg" role="alert" tabIndex={-1} ref={summaryRef}>
                {t("newProfile.unavailable")}
              </div>
            ) : null}
            {errorCount > 0 ? (
              <div className="msg" role="alert">
                {t("newProfile.summary", { count: errorCount })}
              </div>
            ) : null}
            <fieldset>
              <legend>{t("newProfile.profileLanguage")}</legend>
              <div className="radios">
                {(["en", "fr"] as const).map((language) => (
                  <label key={language} lang={language}>
                    <input
                      type="radio"
                      name="profile-language"
                      value={language}
                      checked={profileLanguage === language}
                      onChange={() => setChosen(language)}
                    />
                    {NAMES[language]}
                  </label>
                ))}
              </div>
            </fieldset>
            <FormField
              label={`${t("newProfile.name")} ${t("newProfile.required")}`}
              value={name}
              onChange={(event) => setName(event.target.value)}
              error={errors.name}
              help={t("newProfile.nameHelp")}
              inputRef={nameRef}
              autoComplete="off"
              maxLength={300}
            />
            <fieldset className="group">
              <legend>{t("newProfile.hints")}</legend>
              <p className="help">{t("newProfile.hintsHelp")}</p>
              <FormField
                label={t("identity.website")}
                type="text"
                inputMode="url"
                placeholder="www.example.com"
                value={website}
                onChange={(event) => setWebsite(event.target.value)}
                error={errors.website}
                help={t("newProfile.websiteHelp")}
                inputRef={websiteRef}
                autoComplete="off"
              />
              <div className="fld">
                <label htmlFor={countryId}>{t("identity.country")}</label>
                <select
                  id={countryId}
                  value={country}
                  onChange={(event) => setCountry(event.target.value)}
                >
                  <option value="">{t("newProfile.countryNone")}</option>
                  {countries.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </div>
              <FormField
                label={t("identity.sector")}
                value={sector}
                onChange={(event) => setSector(event.target.value)}
                placeholder={t("newProfile.sectorPlaceholder")}
                autoComplete="off"
              />
            </fieldset>
            <div className="form-actions">
              <Button type="submit" loading={submitting} loadingLabel={t("newProfile.searching")}>
                {t("newProfile.submit")}
              </Button>
              <Link className="btn btn-text" to="/workspace">
                {t("newProfile.cancel")}
              </Link>
            </div>
          </form>
        ) : null}
      </div>
    </section>
  );
}

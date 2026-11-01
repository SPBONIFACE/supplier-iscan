import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet, useLocation } from "react-router";
import { useAuth } from "../auth/AuthContext";
import { LANGUAGES, type Language, setLanguage } from "../i18n";
import { Button, MessageBanner } from "./ui";

const NAMES: Record<Language, string> = { en: "English", fr: "Français" };

function LanguageSwitcher() {
  const { t, i18n } = useTranslation();
  return (
    <fieldset className="lang" aria-label={t("nav.language")}>
      {LANGUAGES.map((language, index) => (
        <span key={language}>
          {index > 0 ? " · " : null}
          <button
            type="button"
            className="link"
            lang={language}
            aria-current={i18n.language === language ? "true" : undefined}
            aria-label={t("nav.switchTo", { language: NAMES[language], lng: language })}
            onClick={() => void setLanguage(language)}
          >
            {language.toUpperCase()}
          </button>
        </span>
      ))}
    </fieldset>
  );
}

/** Top bar, skip link, content area and footer shared by every screen (approved layout, mock-ups #4 and #7; legal footer is #47). */
export function Layout() {
  const { t } = useTranslation();
  const { user, signOut, signOutFailed } = useAuth();
  const { pathname } = useLocation();
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);

  // After a navigation, keyboard and screen-reader users start at the new content.
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    main.current?.focus();
  }, [pathname]);

  return (
    <>
      <a className="skip" href="#content">
        {t("app.skipToContent")}
      </a>
      <header className="topbar">
        <div className="in">
          <Link className="brand" to="/">
            {t("app.name")}
          </Link>
          {user ? (
            <nav aria-label={t("nav.main")}>
              <ul className="nav">
                <li>
                  <NavLink to="/workspace">{t("nav.profiles")}</NavLink>
                </li>
                {user.role === "admin" ? (
                  <li>
                    <NavLink to="/admin">{t("nav.admin")}</NavLink>
                  </li>
                ) : null}
              </ul>
            </nav>
          ) : null}
          <div className="tb-right">
            <LanguageSwitcher />
            {user ? (
              <>
                <span className="who">{user.email}</span>
                <Button variant="text" onClick={() => void signOut()}>
                  {t("nav.signOut")}
                </Button>
              </>
            ) : null}
          </div>
        </div>
      </header>
      <main className="wrap" id="content" tabIndex={-1} ref={main}>
        {signOutFailed ? (
          <MessageBanner kind="error">{t("login.unavailable")}</MessageBanner>
        ) : null}
        <Outlet />
      </main>
    </>
  );
}

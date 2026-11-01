import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { useAuth } from "../auth/AuthContext";
import { homePath } from "../auth/paths";
import { MessageBanner } from "../components/ui";
import { useTitle } from "../lib/useTitle";

/** Placeholder inside the approved layout; the screen itself is built by the issue that owns the route. */
export function Placeholder({ titleKey, bodyKey }: { titleKey: string; bodyKey: string }) {
  const { t } = useTranslation();
  useTitle(t(titleKey));
  return (
    <section>
      <h1>{t(titleKey)}</h1>
      <MessageBanner kind="note">{t(bodyKey)}</MessageBanner>
    </section>
  );
}

/** Unknown route, or a 404 from the API (an item that does not exist or is not the user's). */
export function NotFoundPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  useTitle(t("notFound.title"));
  return (
    <section className="center">
      <h1>{t("notFound.title")}</h1>
      <MessageBanner kind="note">{t("notFound.body")}</MessageBanner>
      <p>
        <Link to={user ? homePath(user) : "/login"}>{t("notFound.home")}</Link>
      </p>
    </section>
  );
}

import { type FormEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useSearchParams } from "react-router";
import { useAuth } from "../auth/AuthContext";
import { homePath, safeNext } from "../auth/paths";
import { Button, FormField, MessageBanner } from "../components/ui";
import { api } from "../lib/api";
import { useTitle } from "../lib/useTitle";

export function LoginPage() {
  const { t } = useTranslation();
  const { user, status, setUser } = useAuth();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ email?: string; password?: string }>({});
  const [banner, setBanner] = useState<"invalid" | "unavailable" | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  useTitle(t("login.title"));

  if (status === "ready" && user) return <Navigate to={next ?? homePath(user)} replace />;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    const found = {
      email: email.trim() ? undefined : t("login.emailRequired"),
      password: password ? undefined : t("login.passwordRequired"),
    };
    setErrors(found);
    setBanner(null);
    if (found.email || found.password) {
      (found.email ? emailRef : passwordRef).current?.focus();
      return; // an empty field is flagged inline and no request is sent
    }
    setSubmitting(true);
    const result = await api.login(email, password);
    setSubmitting(false);
    if (result.ok) {
      setUser(result.data);
      return;
    }
    // Unknown email and wrong password give the same message.
    setBanner(result.kind === "unavailable" ? "unavailable" : "invalid");
    if (result.kind !== "unavailable") {
      setPassword("");
      passwordRef.current?.focus();
    }
  }

  return (
    <div className="center">
      <h1>{t("login.title")}</h1>
      {banner ? <MessageBanner kind="error">{t(`login.${banner}`)}</MessageBanner> : null}
      <form className="form" noValidate onSubmit={onSubmit}>
        <FormField
          label={t("login.email")}
          type="email"
          autoComplete="username"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          error={errors.email}
          inputRef={emailRef}
        />
        <FormField
          label={t("login.password")}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={errors.password}
          inputRef={passwordRef}
        />
        <div className="form-actions">
          <Button type="submit" loading={submitting} loadingLabel={t("login.submitting")}>
            {t("login.submit")}
          </Button>
        </div>
      </form>
      <p className="meta">{t("login.invitationOnly")}</p>
      <p>
        <Link to="/demo">{t("demo.explore")}</Link>
      </p>
    </div>
  );
}

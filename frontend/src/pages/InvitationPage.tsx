import { type FormEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";
import { useAuth } from "../auth/AuthContext";
import { homePath } from "../auth/paths";
import { Button, FormField, LoadingIndicator, MessageBanner } from "../components/ui";
import { api, type InvitationCheck } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useTitle } from "../lib/useTitle";

type Check =
  | { state: "loading" }
  | { state: "valid"; invitation: InvitationCheck }
  | { state: "invalid" }
  | { state: "unavailable" };

type Errors = { password?: string; confirm?: string };

// The token stays in the URL only: it is never stored, logged or put in a message.
export function InvitationPage() {
  const { t, i18n } = useTranslation();
  const { token = "" } = useParams();
  const { user, status, setUser, signOut } = useAuth();
  const navigate = useNavigate();
  const [check, setCheck] = useState<Check>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [step, setStep] = useState<"landing" | "form">("landing");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Errors>({});
  const [banner, setBanner] = useState<"unavailable" | null>(null);
  const [seatLimit, setSeatLimit] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const summary = useRef<HTMLDivElement>(null);
  const signedIn = status === "ready" && user !== null;

  useTitle(t("invitation.eyebrow"));

  useEffect(() => {
    if (status !== "ready" || signedIn) return;
    let current = true;
    setCheck({ state: "loading" });
    void api.checkInvitation(token).then((result) => {
      if (!current) return;
      if (result.ok) setCheck({ state: "valid", invitation: result.data });
      else setCheck({ state: result.kind === "unavailable" ? "unavailable" : "invalid" });
    });
    return () => {
      current = false;
    };
  }, [token, status, signedIn, attempt]);

  if (status === "loading") return <LoadingIndicator />;

  if (user) {
    return (
      <div className="center">
        <h1>{t("invitation.signedInTitle")}</h1>
        <MessageBanner kind="note">{t("invitation.signedInBody")}</MessageBanner>
        <p className="actions">
          <Button onClick={() => void signOut()}>{t("nav.signOut")}</Button>
        </p>
      </div>
    );
  }

  if (check.state === "loading") return <LoadingIndicator />;

  if (check.state === "unavailable") {
    return (
      <div className="center">
        <h1>{t("invitation.eyebrow")}</h1>
        <MessageBanner kind="error">{t("invitation.unavailable")}</MessageBanner>
        <p className="actions">
          <Button variant="secondary" onClick={() => setAttempt((n) => n + 1)}>
            {t("common.retry")}
          </Button>
        </p>
      </div>
    );
  }

  // One shared message for a used, expired, revoked or unknown token: no account detail.
  if (check.state === "invalid") {
    return (
      <div className="center">
        <span className="micro eyebrow">{t("invitation.eyebrow")}</span>
        <h1>{t("invitation.invalidTitle")}</h1>
        <MessageBanner kind="note">{t("invitation.invalidBody")}</MessageBanner>
        <p className="prose">{t("invitation.askAdmin")}</p>
        <p>
          <Link to="/login">{t("invitation.signInIfAccount")}</Link>
        </p>
      </div>
    );
  }

  const { invitation } = check;

  if (seatLimit) {
    return (
      <div className="center">
        <span className="micro eyebrow">
          {t("invitation.eyebrowOrganisation", { organisation: invitation.organisation_name })}
        </span>
        <h1>{t("invitation.seatTitle")}</h1>
        <MessageBanner kind="note">{t("invitation.seatBody")}</MessageBanner>
        <p className="prose">{t("invitation.seatAskAdmin")}</p>
        <p>
          <Link to="/login">{t("invitation.signInIfAccount")}</Link>
        </p>
      </div>
    );
  }

  if (step === "landing") {
    return (
      <div className="center">
        <span className="micro eyebrow">{t("invitation.eyebrow")}</span>
        <h1>{t("invitation.joinTitle", { organisation: invitation.organisation_name })}</h1>
        <p className="prose">{t("invitation.intro")}</p>
        <dl className="kv">
          <dt>{t("invitation.invitedEmail")}</dt>
          <dd>{invitation.email}</dd>
          <dt>{t("invitation.organisation")}</dt>
          <dd>{invitation.organisation_name}</dd>
          <dt>{t("invitation.validUntil")}</dt>
          <dd>
            {formatDateTime(invitation.expires_at, i18n.language)} · {t("invitation.singleUse")}
          </dd>
        </dl>
        <div className="form-actions">
          <Button onClick={() => setStep("form")}>{t("invitation.start")}</Button>
        </div>
        <p className="meta">{t("invitation.notYou")}</p>
      </div>
    );
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    const found: Errors = {
      password: password ? undefined : t("invitation.passwordRequired"),
      confirm: !confirm
        ? t("invitation.confirmRequired")
        : confirm !== password
          ? t("invitation.mismatch")
          : undefined,
    };
    setBanner(null);
    setErrors(found);
    if (found.password || found.confirm) {
      summary.current?.focus();
      return;
    }
    setSubmitting(true);
    const result = await api.acceptInvitation(token, password);
    setSubmitting(false);
    if (result.ok) {
      setUser(result.data); // signed in directly, no second sign-in
      navigate(homePath(result.data), { replace: true });
    } else if (result.kind === "validation") {
      setErrors({ password: t("invitation.passwordRejected") });
      summary.current?.focus();
    } else if (result.kind === "conflict") {
      setSeatLimit(true);
    } else if (result.kind === "not_found") {
      setCheck({ state: "invalid" });
    } else {
      setBanner("unavailable");
    }
  }

  const count = [errors.password, errors.confirm].filter(Boolean).length;

  return (
    <div className="center">
      <span className="micro eyebrow">
        {t("invitation.eyebrowOrganisation", { organisation: invitation.organisation_name })}
      </span>
      <h1>{t("invitation.formTitle")}</h1>
      {count > 0 ? (
        <div className="msg" role="alert" tabIndex={-1} ref={summary}>
          <strong>{t("invitation.summary", { count })}</strong>
        </div>
      ) : null}
      {banner ? <MessageBanner kind="error">{t(`invitation.${banner}`)}</MessageBanner> : null}
      <form className="form" noValidate onSubmit={onSubmit}>
        <FormField
          label={t("login.email")}
          type="email"
          value={invitation.email}
          readOnly
          help={t("invitation.emailHelp")}
        />
        <FormField
          label={t("invitation.password")}
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          error={errors.password}
          help={t("invitation.passwordHelp")}
        />
        <FormField
          label={t("invitation.confirm")}
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
          error={errors.confirm}
        />
        <div className="form-actions">
          <Button type="submit" loading={submitting} loadingLabel={t("invitation.submitting")}>
            {t("invitation.submit")}
          </Button>
        </div>
      </form>
    </div>
  );
}

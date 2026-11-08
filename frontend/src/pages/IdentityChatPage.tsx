import { type FormEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate, useParams } from "react-router";
import { CandidateCard } from "../components/CandidateCard";
import { Button, FormField, LoadingIndicator } from "../components/ui";
import {
  type ApiFailure,
  api,
  type IdentityCandidate,
  type IdentitySession,
  type IdentityTurn,
} from "../lib/api";
import { countryName } from "../lib/format";
import { useTitle } from "../lib/useTitle";
import { NotFoundPage } from "./Simple";

type Busy = "message" | "candidates" | "website" | "confirm" | null;

const time = (value: string, language: string) =>
  new Date(value).toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" });

export function IdentityChatPage() {
  const { t, i18n } = useTranslation();
  const { sessionId = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const passed = (location.state as { session?: IdentitySession } | null)?.session;
  const [session, setSession] = useState<IdentitySession | null>(
    passed?.id === sessionId ? passed : null,
  );
  const [loadFailure, setLoadFailure] = useState<ApiFailure | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const inflight = useRef(false);
  const [others, setOthers] = useState<IdentityCandidate[] | null>(null);
  const [selected, setSelected] = useState<IdentityCandidate | null>(null);
  const [websiteMode, setWebsiteMode] = useState(false);
  const [website, setWebsite] = useState("");
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [startedIdentity, setStartedIdentity] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const log = useRef<HTMLOListElement>(null);
  useTitle(t("chat.title"));

  useEffect(() => {
    if (session) return;
    let cancelled = false;
    void api.getIdentitySession(sessionId).then((result) => {
      if (cancelled) return;
      if (result.ok) setSession(result.data);
      else setLoadFailure(result);
    });
    return () => {
      cancelled = true;
    };
  }, [session, sessionId, attempt]);

  // Focus is never lost: when the buttons that had it go away, it moves to the newest turn.
  useEffect(() => {
    if (tick > 0) (log.current?.lastElementChild as HTMLElement | null)?.focus();
  }, [tick]);

  if (loadFailure?.kind === "not_found") return <NotFoundPage />;
  if (loadFailure) {
    return (
      <section>
        <h1>{t("chat.title")}</h1>
        <div role="alert" className="msg">
          <p>{t("chat.agentUnavailable")}</p>
          <div className="actions">
            <Button
              variant="secondary"
              onClick={() => {
                setLoadFailure(null);
                setAttempt((n) => n + 1);
              }}
            >
              {t("common.retry")}
            </Button>
          </div>
        </div>
      </section>
    );
  }
  if (!session) {
    return (
      <section>
        <h1>{t("chat.title")}</h1>
        <LoadingIndicator />
      </section>
    );
  }

  const current: IdentitySession = session;
  const turns = current.turns;
  const last = turns[turns.length - 1];
  const registriesDown =
    current.registries.gleif === "unreachable" && current.registries.wikidata === "unreachable";
  const lastProposal = [...turns].reverse().find((turn) => turn.kind === "proposal");
  const offersCandidate =
    current.status === "open" &&
    !registriesDown &&
    last !== undefined &&
    (last.kind === "proposal" || (last.kind === "error" && lastProposal !== undefined)) &&
    !startedIdentity;
  const proposed = last?.kind === "proposal" ? last : lastProposal;
  const showWebsite =
    current.status === "open" &&
    (websiteMode || registriesDown || last?.kind === "website_rejected");
  const ready = turns[0]?.kind === "disclosure";
  const rejection = last?.kind === "website_rejected" ? last.text : null;
  const hints = [
    current.hints.sector ? t("chat.hintSector", { value: current.hints.sector }) : null,
    current.hints.country
      ? t("chat.hintCountry", { value: countryName(current.hints.country, i18n.language) })
      : null,
    current.hints.website ? t("chat.hintWebsite", { value: current.hints.website }) : null,
  ].filter(Boolean);

  // Failures other than a plain "no" are said in the chat, never as an error page.
  function fail(result: ApiFailure) {
    if (result.kind === "unauthorized") return; // the app sends the member to sign in
    if (result.kind === "not_found") setLoadFailure(result);
    else setProblem(t("chat.agentUnavailable"));
  }

  async function run<T>(kind: Exclude<Busy, null>, work: () => Promise<T>): Promise<T | null> {
    if (inflight.current) return null;
    inflight.current = true;
    setBusy(kind);
    setProblem(null);
    try {
      return await work();
    } finally {
      inflight.current = false;
      setBusy(null);
    }
  }

  function accept(next: IdentitySession) {
    setSession(next);
    setOthers(null);
    setSelected(null);
    setWebsiteMode(false);
    setWebsite("");
    setTick((n) => n + 1);
  }

  async function onSend(event: FormEvent) {
    event.preventDefault();
    const message = text.trim();
    if (!message || !ready) return;
    await run("message", async () => {
      const result = await api.sendIdentityMessage(current.id, message);
      if (result.ok) {
        setText("");
        setSession(result.data);
        setOthers(null);
        setSelected(null);
        setWebsiteMode(false);
      } else fail(result);
    });
  }

  async function onShowOthers() {
    await run("candidates", async () => {
      const result = await api.listIdentityCandidates(current.id);
      if (result.ok) {
        setOthers(result.data.candidates);
        setTick((n) => n + 1);
      } else fail(result);
    });
  }

  async function onWebsite(event: FormEvent) {
    event.preventDefault();
    const value = website.trim();
    if (!value) return;
    await run("website", async () => {
      const result = await api.submitIdentityWebsite(current.id, value);
      if (result.ok) accept(result.data);
      else if (result.kind === "validation")
        setProblem(result.errors[0]?.message ?? t("chat.websiteInvalid"));
      else fail(result);
    });
  }

  async function onConfirm(candidate: IdentityCandidate) {
    await run("confirm", async () => {
      let identityId = startedIdentity ?? current.identity_id;
      if (!identityId) {
        const confirmed = await api.confirmIdentity(current.id, candidate.id);
        if (confirmed.ok) identityId = confirmed.data.identity_id;
        else if (confirmed.kind === "conflict") {
          // Already confirmed (double click): carry on with the stored identity.
          const again = await api.getIdentitySession(current.id);
          if (again.ok) identityId = again.data.identity_id;
        } else return fail(confirmed);
        if (!identityId) return setProblem(t("chat.agentUnavailable"));
        setStartedIdentity(identityId); // kept if the start is refused
      }
      const started = await api.startRun(identityId);
      if (started.ok) navigate(`/profiles/${started.data.id}/run`);
      else if (started.kind === "refused") {
        setRefusal(started.reason ?? "unknown");
        setTick((n) => n + 1);
      } else if (started.kind !== "conflict") fail(started);
    });
  }

  const turnBody = (turn: IdentityTurn) => {
    if (turn.kind === "disclosure") return <p className="disclosure">{turn.text}</p>;
    if (turn.kind === "error")
      return (
        <div className="msg" role="alert">
          {turn.text}
        </div>
      );
    return (
      <>
        <p className={turn.role === "user" ? "said" : undefined}>{turn.text}</p>
        {turn.candidate ? <CandidateCard candidate={turn.candidate} /> : null}
      </>
    );
  };

  const refusalText = refusal
    ? t(`chat.refused.${refusal}`, { defaultValue: t("chat.refused.unknown") })
    : null;

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
      <h1>{t("chat.title")}</h1>
      <p className="meta">{[t("chat.search", { name: current.name }), ...hints].join(" · ")}</p>
      <div className="chat">
        <ol className="ts" role="log" aria-label={t("chat.log")}>
          {turns.map((turn, index) => {
            const isLast = index === turns.length - 1;
            return (
              <li
                key={turn.id}
                className={turn.role === "user" ? "turn turn-you" : "turn turn-ai"}
                tabIndex={isLast ? -1 : undefined}
              >
                <div className="turn-h">
                  <span className={turn.role === "user" ? "ml ml-ink" : "ml"}>
                    {turn.role === "user" ? t("chat.you") : t("chat.assistant")}
                  </span>
                  <span className="meta">{time(turn.created_at, i18n.language)}</span>
                </div>
                {turnBody(turn)}
                {isLast ? (
                  <>
                    {busy === "message" || busy === "candidates" || busy === "website" ? (
                      <LoadingIndicator />
                    ) : null}
                    {offersCandidate && !selected && !others && proposed?.candidate ? (
                      <div className="actions">
                        <Button
                          onClick={() => proposed.candidate && setSelected(proposed.candidate)}
                        >
                          {t("chat.thisIsIt")}
                        </Button>
                        <Button variant="secondary" onClick={() => void onShowOthers()}>
                          {t("chat.showOthers")}
                        </Button>
                        <Button variant="text" onClick={() => setWebsiteMode(true)}>
                          {t("chat.noneOfThese")}
                        </Button>
                      </div>
                    ) : null}
                    {others && !selected ? (
                      <div>
                        <p>{t(others.length ? "chat.othersIntro" : "chat.noOthers")}</p>
                        {others.map((candidate, i) => (
                          <div key={candidate.id}>
                            <CandidateCard
                              candidate={candidate}
                              title={`${i + 2}. ${candidate.legal_name}`}
                            />
                            <div className="actions">
                              <Button variant="secondary" onClick={() => setSelected(candidate)}>
                                {t("chat.select", { name: candidate.legal_name })}
                              </Button>
                            </div>
                          </div>
                        ))}
                        <div className="actions">
                          <Button variant="text" onClick={() => setWebsiteMode(true)}>
                            {t("chat.noneOfThese")}
                          </Button>
                        </div>
                      </div>
                    ) : null}
                    {selected ? (
                      <div>
                        <p>{t("chat.checkRecord")}</p>
                        <CandidateCard candidate={selected} title={t("chat.record")} record />
                        {refusalText ? (
                          <div className="msg" role="alert">
                            {refusalText}
                          </div>
                        ) : null}
                        <div className="actions">
                          <Button
                            loading={busy === "confirm"}
                            loadingLabel={t("chat.starting")}
                            onClick={() => void onConfirm(selected)}
                          >
                            {startedIdentity ? t("chat.startAgain") : t("chat.confirm")}
                          </Button>
                          {startedIdentity ? null : (
                            <Button variant="secondary" onClick={() => setSelected(null)}>
                              {t("chat.correct")}
                            </Button>
                          )}
                        </div>
                      </div>
                    ) : null}
                    {showWebsite && !selected ? (
                      <form className="form" noValidate onSubmit={onWebsite}>
                        <FormField
                          label={t("chat.websiteLabel")}
                          value={website}
                          onChange={(event) => setWebsite(event.target.value)}
                          error={rejection ? `${t("common.errorPrefix")} ${rejection}` : null}
                          help={t("chat.websiteHelp")}
                          autoComplete="off"
                          inputMode="url"
                        />
                        <div className="actions">
                          <Button
                            type="submit"
                            loading={busy === "website"}
                            loadingLabel={t("chat.checking")}
                          >
                            {t("chat.useWebsite")}
                          </Button>
                          {!registriesDown && proposed ? (
                            <Button
                              variant="text"
                              onClick={() => {
                                setWebsiteMode(false);
                                setTick((n) => n + 1);
                              }}
                            >
                              {t("chat.back")}
                            </Button>
                          ) : null}
                        </div>
                      </form>
                    ) : null}
                  </>
                ) : null}
              </li>
            );
          })}
        </ol>
        {problem ? (
          <div className="msg" role="alert">
            {problem}
          </div>
        ) : null}
        {current.status === "open" ? (
          <form className="composer" onSubmit={onSend}>
            <div className="row">
              <div className="fld">
                <label id="reply-label" htmlFor="reply">
                  {t("chat.reply")}
                </label>
                <textarea
                  id="reply"
                  rows={2}
                  value={text}
                  disabled={!ready}
                  aria-describedby="reply-help"
                  onChange={(event) => setText(event.target.value)}
                />
                <p className="help" id="reply-help">
                  {t("chat.replyHelp")}
                </p>
              </div>
              <Button
                type="submit"
                disabled={!ready}
                loading={busy === "message"}
                loadingLabel={t("chat.sending")}
              >
                {t("chat.send")}
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </section>
  );
}

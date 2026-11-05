// Run progress (spec Flow 1 steps 4-5, F2, F7; mock-ups 04-run-progress-*): where a profile run is, the
// sources excluded at the site owner's request, the failure log, the remaining quota, Stop and Resume.
// The screen polls GET /runs/{id} while the run is queued, running or paused (see useRunProgress).
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";
import { FlagBanner } from "../components/FlagBanner";
import { Button, LoadingIndicator, MessageBanner } from "../components/ui";
import {
  api,
  type MemberOrganisation,
  type ProfileDefinition,
  type Run,
  type RunFailure,
  type RunStage,
} from "../lib/api";
import { formatDate, formatDateTime, formatNumber } from "../lib/format";
import { isActive, useRunProgress } from "../lib/useRunProgress";
import { useTitle } from "../lib/useTitle";
import { NotFoundPage } from "./Simple";

const STAGES: RunStage[] = ["identity", "collection", "extraction", "assessment"];
const HAS_PROFILE = ["partial", "completed"];

type StageState =
  | "done"
  | "waiting"
  | "notStarted"
  | "running"
  | "paused"
  | "stopped"
  | "failed"
  | "partial";

/** The state word of each stage. A stage is never told by colour alone: the word is always shown. */
export function stageStates(run: Run): { stage: RunStage; state: StageState; current: boolean }[] {
  const index = STAGES.indexOf(run.stage);
  return STAGES.map((stage, position) => {
    if (run.status === "completed") return { stage, state: "done", current: false };
    if (position < index) return { stage, state: "done", current: false };
    if (position > index) {
      return { stage, state: isActive(run.status) ? "waiting" : "notStarted", current: false };
    }
    const own: Record<Run["status"], StageState> = {
      queued: "waiting",
      running: "running",
      paused: "paused",
      stopped: "stopped",
      failed: "failed",
      insufficient_sources: "failed",
      partial: "partial",
      completed: "done",
    };
    return { stage, state: own[run.status], current: true };
  });
}

type ActionNotice = { kind: "note" | "error"; text: string } | null;

export function RunPage() {
  const { t, i18n } = useTranslation();
  const { profileId = "" } = useParams();
  const { load, data, unreachable, refresh, retry, apply } = useRunProgress(profileId);
  const [organisation, setOrganisation] = useState<MemberOrganisation | null>(null);
  const [definition, setDefinition] = useState<ProfileDefinition | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState<"stop" | "resume" | null>(null);
  const [notice, setNotice] = useState<ActionNotice>(null);
  const sending = useRef(false);
  const stopButton = useRef<HTMLButtonElement>(null);
  const confirmTitle = useRef<HTMLHeadingElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  const run = data?.run ?? null;
  const supplierName = run ? (run.supplier_name ?? t("workspace.nameHidden")) : "";
  useTitle(run ? `${supplierName} · ${t("titles.run")}` : t("titles.run"));

  // The quota is read at the first load and once more when the run ends (it may have changed).
  const ended = run ? !isActive(run.status) : null;
  useEffect(() => {
    if (ended === null) return;
    let current = true;
    void api.getOrganisation().then((result) => {
      if (current && result.ok) setOrganisation(result.data);
    });
    return () => {
      current = false;
    };
  }, [ended]);

  // Labels of the sections a partial run did not cover.
  const partial = run?.status === "partial";
  const language = i18n.language === "fr" ? "fr" : "en";
  useEffect(() => {
    if (!partial) return;
    let current = true;
    void api.getProfileDefinition(language).then((result) => {
      if (current && result.ok) setDefinition(result.data);
    });
    return () => {
      current = false;
    };
  }, [partial, language]);

  useEffect(() => {
    if (confirming) confirmTitle.current?.focus();
  }, [confirming]);

  const closeConfirm = useCallback(() => {
    setConfirming(false);
    stopButton.current?.focus();
  }, []);

  const act = useCallback(
    async (kind: "stop" | "resume") => {
      if (sending.current) return;
      sending.current = true;
      setBusy(kind);
      setNotice(null);
      const result =
        kind === "stop" ? await api.stopRun(profileId) : await api.resumeRun(profileId);
      sending.current = false;
      setBusy(null);
      if (result.ok) {
        apply(result.data);
        heading.current?.focus();
        return;
      }
      if (result.kind === "conflict") {
        setNotice({
          kind: "note",
          text: t(kind === "stop" ? "run.stopFinished" : "run.resumeNotPaused"),
        });
        await refresh();
      } else if (result.kind !== "unauthorized") {
        setNotice({
          kind: "error",
          text: t(kind === "stop" ? "run.stopFailed" : "run.resumeFailed"),
        });
      }
    },
    [apply, profileId, refresh, t],
  );

  if (load === "not_found") return <NotFoundPage />;
  if (load === "loading" || (load === "ready" && !run)) {
    return (
      <>
        <h1>{t("titles.run")}</h1>
        <LoadingIndicator />
      </>
    );
  }
  if (load === "error" || !data || !run) {
    return (
      <>
        <h1>{t("titles.run")}</h1>
        <MessageBanner kind="error">
          <p>{t("run.loadError")}</p>
          <p>
            <button type="button" className="btn btn-secondary" onClick={retry}>
              {t("common.retry")}
            </button>
          </p>
        </MessageBanner>
      </>
    );
  }

  const stages = stageStates(run);
  const currentIndex = Math.max(0, STAGES.indexOf(run.stage));
  const stageName = (stage: RunStage) => t(`run.stages.${stage}`);
  const lower = (text: string) => text.toLocaleLowerCase(i18n.language);
  const when = (value: string) => formatDateTime(value, i18n.language);
  const failures = data.failures;
  const active = isActive(run.status);
  const canStop = active && !run.stop_requested;
  const pauseReason = run.pause_dependency
    ? t(`run.pauseReason.${run.pause_dependency}`, { defaultValue: run.pause_reason ?? "" })
    : (run.pause_reason ?? "");

  const detail = (stage: RunStage, state: StageState): string | null => {
    const parts: string[] = [];
    if (stage === "identity" && state === "done") {
      parts.push(t("run.detail.identity", { date: when(run.created_at) }));
    }
    if (stage === "collection" && state !== "waiting" && state !== "notStarted") {
      if (run.status === "insufficient_sources") {
        parts.push(t("run.detail.noUsable"));
      } else {
        if (data.sourceCount !== null) {
          parts.push(
            t(state === "running" ? "run.detail.sourcesSoFar" : "run.detail.sources", {
              count: data.sourceCount,
            }),
          );
        }
        if (run.excluded_sources.length > 0) {
          parts.push(t("run.detail.excluded", { count: run.excluded_sources.length }));
        }
        if (failures && failures.length > 0) {
          parts.push(t("run.detail.failures", { count: failures.length }));
        }
      }
    }
    if (stage === "extraction") {
      if (state === "paused" && pauseReason)
        parts.push(t("run.detail.paused", { reason: pauseReason }));
      else if (state === "done" && run.proposed_facts > 0) {
        parts.push(t("run.detail.facts", { count: run.proposed_facts }));
      }
    }
    return parts.length > 0 ? parts.join(" · ") : null;
  };

  const summary =
    run.status === "completed"
      ? t("run.summary.completed")
      : t(`run.summary.${run.status}`, {
          n: currentIndex + 1,
          stage: lower(stageName(run.stage)),
        });

  const startedAt = run.started_at ?? run.created_at;
  const quota = (() => {
    if (!organisation) return null;
    if (organisation.profiles_remaining === null) return t("workspace.quotaUnlimited");
    const remaining = formatNumber(organisation.profiles_remaining, i18n.language);
    return organisation.profile_quota === null
      ? t("workspace.quotaRemaining", { remaining })
      : t("workspace.quotaRemainingOf", {
          remaining,
          quota: formatNumber(organisation.profile_quota, i18n.language),
        });
  })();

  const sectionLabel = (id: string): string => {
    if (id === "recommendations") return t("run.recommendations");
    return definition?.sections.find((section) => section.id === id)?.label ?? id;
  };

  return (
    <>
      <nav className="crumb" aria-label={t("run.breadcrumb")}>
        <ol>
          <li>
            <Link to="/workspace">{t("run.profiles")}</Link>
          </li>
          <li aria-current="page">{supplierName}</li>
        </ol>
      </nav>

      <div className="ph">
        <div>
          <h1 ref={heading} tabIndex={-1}>
            {supplierName}
          </h1>
          <p className="meta">
            {t("run.status", { status: t(`workspace.statuses.${run.status}`) })} ·{" "}
            {t("run.started", { date: when(startedAt) })}
            {run.finished_at ? ` · ${t("run.ended", { date: when(run.finished_at) })}` : null}
          </p>
        </div>
        <div className="ph-actions">
          {canStop ? (
            <button
              type="button"
              ref={stopButton}
              className="btn btn-secondary"
              aria-expanded={confirming}
              aria-controls={confirming ? "stop-dialog" : undefined}
              disabled={busy !== null}
              onClick={() => setConfirming(true)}
            >
              {t("run.stop")}
            </button>
          ) : null}
          {HAS_PROFILE.includes(run.status) ? (
            <Link className="btn btn-primary" to={`/profiles/${run.id}`}>
              {t("run.openCard")}
            </Link>
          ) : null}
          {!active && !HAS_PROFILE.includes(run.status) ? (
            <Link className="btn btn-secondary" to="/workspace">
              {t("run.backToProfiles")}
            </Link>
          ) : null}
        </div>
      </div>

      {run.stop_requested && active ? (
        <MessageBanner kind="note">
          <p>{t("run.stopRequested")}</p>
        </MessageBanner>
      ) : null}

      {confirming && canStop ? (
        <section
          className="confirm"
          id="stop-dialog"
          role="alertdialog"
          aria-labelledby="stop-title"
          aria-describedby="stop-body"
          onKeyDown={(event) => {
            if (event.key === "Escape") closeConfirm();
          }}
        >
          <h2 id="stop-title" ref={confirmTitle} tabIndex={-1}>
            {t("run.stopTitle")}
          </h2>
          <p id="stop-body">
            {run.supplier_name
              ? t("run.stopBody", { name: run.supplier_name })
              : t("run.stopBodyNoName")}
          </p>
          <div className="actions">
            <Button
              loading={busy === "stop"}
              onClick={async () => {
                setConfirming(false);
                await act("stop");
              }}
            >
              {t("run.stopConfirm")}
            </Button>
            <Button variant="secondary" onClick={closeConfirm}>
              {t("run.keepRunning")}
            </Button>
          </div>
        </section>
      ) : null}

      {notice ? (
        <MessageBanner kind={notice.kind}>
          <p>{notice.text}</p>
        </MessageBanner>
      ) : null}

      {unreachable ? (
        <MessageBanner kind="note">
          <p>{t("run.unreachable")}</p>
        </MessageBanner>
      ) : null}

      {run.status === "paused" ? (
        <MessageBanner kind="error">
          <p>
            <span className="pfx">{t("common.errorPrefix")}</span> {pauseReason}
          </p>
          <p>{t("run.pausedBody", { stage: lower(stageName(run.stage)) })}</p>
          <div className="actions">
            <Button
              loading={busy === "resume"}
              disabled={busy === "stop"}
              onClick={() => void act("resume")}
            >
              {t("run.resume")}
            </Button>
          </div>
        </MessageBanner>
      ) : null}

      {run.status === "failed" ? (
        <MessageBanner kind="error">
          <p>
            <span className="pfx">{t("common.errorPrefix")}</span>{" "}
            {run.error ?? t("run.failedNoReason")}
          </p>
          <p>{t("run.failedBody")}</p>
        </MessageBanner>
      ) : null}

      {run.status === "stopped" ? (
        <MessageBanner kind="note">
          <p>
            <span className="pfx">{t("workspace.notePrefix")}</span>{" "}
            {t("run.stoppedNote", {
              when: run.finished_at ? t("run.stoppedAt", { date: when(run.finished_at) }) : "",
            })}
          </p>
        </MessageBanner>
      ) : null}

      {run.status === "completed" ? (
        <MessageBanner kind="note">
          <p>
            <span className="pfx">{t("workspace.notePrefix")}</span> {t("run.completedNote")}
          </p>
        </MessageBanner>
      ) : null}

      {run.status === "insufficient_sources" ? (
        <FlagBanner label={t("run.insufficientLabel")}>
          <p>{t("run.insufficientBody")}</p>
          <p>
            <Link to="/profiles/new">{t("run.insufficientLink")}</Link>
          </p>
        </FlagBanner>
      ) : null}

      {run.status === "partial" ? (
        <FlagBanner label={t("run.partialLabel")}>
          <p>{t("run.partialBody")}</p>
          <p>{t("run.partialSections")}:</p>
          <ul>
            {run.uncovered_sections.map((id) => (
              <li key={id}>{sectionLabel(id)}</li>
            ))}
          </ul>
        </FlagBanner>
      ) : null}

      <div className="run">
        <div>
          <section className="sec" aria-labelledby="prog-h">
            <h2 id="prog-h">{t("run.progress")}</h2>
            <p className="summary" role="status">
              {summary}
            </p>
            <ol className="stages">
              {stages.map(({ stage, state, current }, position) => {
                const text = detail(stage, state);
                return (
                  <li key={stage} className="stage" aria-current={current ? "step" : undefined}>
                    <span className="no">{position + 1}</span>
                    <span className="nm">{stageName(stage)}</span>
                    <span className="st">
                      <span
                        className={
                          state === "done"
                            ? "ml"
                            : state === "waiting" || state === "notStarted"
                              ? "ml ml-quiet"
                              : "ml ml-ink"
                        }
                      >
                        {t(`run.stageState.${state}`)}
                      </span>
                    </span>
                    {text ? <span className="dt">{text}</span> : null}
                  </li>
                );
              })}
            </ol>
          </section>

          {run.excluded_sources.length > 0 ? (
            <FlagBanner label={t("run.excludedLabel")}>
              {run.excluded_sources.map((source) => (
                <p key={source.domain}>
                  <span className="mono">{source.domain}</span> {t("run.excludedBody")}
                </p>
              ))}
            </FlagBanner>
          ) : null}

          <FailureLog failures={failures} />
        </div>

        <aside className="aside" aria-labelledby="q-h">
          <section>
            <h2 id="q-h">{t("run.quota")}</h2>
            {quota ? <p>{quota}</p> : null}
            <p className="sm sec-text">{t("run.quotaNote")}</p>
          </section>
          <section>
            <h2>{t("run.thisRun")}</h2>
            <dl className="dl">
              <dt>{t("run.runStatus")}</dt>
              <dd>{t(`workspace.statuses.${run.status}`)}</dd>
              <dt>{t("run.runStarted")}</dt>
              <dd>{formatDate(startedAt, i18n.language)}</dd>
              {run.finished_at ? (
                <>
                  <dt>{t("run.runEnded")}</dt>
                  <dd>{formatDate(run.finished_at, i18n.language)}</dd>
                </>
              ) : null}
            </dl>
            <p className="sm sec-text">{t("run.leaveNote")}</p>
          </section>
        </aside>
      </div>
    </>
  );
}

function FailureLog({ failures }: { failures: RunFailure[] | null }) {
  const { t, i18n } = useTranslation();
  const capReached = failures?.some((failure) => failure.kind === "attempt_cap") ?? false;
  return (
    <section className="sec" aria-labelledby="log-h">
      <h2 id="log-h">{t("run.failureLog")}</h2>
      <p className="sm sec-text">
        {t("run.failureLogIntro")} {capReached ? t("run.attemptCap") : null}
      </p>
      {failures === null ? (
        <p>{t("run.failuresUnknown")}</p>
      ) : failures.length === 0 ? (
        <p>{t("run.noFailures")}</p>
      ) : (
        <table className="tbl">
          <caption className="vh">{t("run.failureLog")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("run.cols.time")}</th>
              <th scope="col">{t("run.cols.source")}</th>
              <th scope="col">{t("run.cols.strategy")}</th>
              <th scope="col">{t("run.cols.what")}</th>
              <th scope="col">{t("run.cols.next")}</th>
            </tr>
          </thead>
          <tbody>
            {failures.map((failure) => (
              <tr key={failure.id}>
                <td data-label={t("run.cols.time")}>
                  {formatDateTime(failure.created_at, i18n.language)}
                </td>
                <td data-label={t("run.cols.source")}>
                  {failure.url ? (
                    <span className="mono">{failure.url}</span>
                  ) : (
                    t("run.retrievalSource")
                  )}
                </td>
                <td data-label={t("run.cols.strategy")}>{t(`run.strategy.${failure.strategy}`)}</td>
                <td data-label={t("run.cols.what")}>
                  {t(`run.kind.${failure.kind}`, { defaultValue: failure.message })}
                </td>
                <td data-label={t("run.cols.next")}>
                  {failure.next_strategy
                    ? t(`run.strategy.${failure.next_strategy}`)
                    : t("run.noNext")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

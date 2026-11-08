// The supplier card (spec F5, F3 display rules; mock-ups 05-supplier-card-*): a side panel over the
// workspace with its own URL. Header, key figures, flags, then one row per fact field of the profile
// definition; each row can be approved or corrected by a member (#36). Below the facts: the assessment
// section (#37). The deletion date (#45) is not here.
import { type RefObject, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useMatch, useNavigate, useParams } from "react-router";
import { DownloadPdf } from "../components/DownloadPdf";
import {
  ExternalLink,
  FactList,
  FactRow,
  IAF_CERTSEARCH_URL,
  QuoteBlock,
  Redacted,
  SourceChip,
  StatusBadge,
} from "../components/evidence";
import type { ReviewBody, ReviewControls, ReviewOutcome } from "../components/FactReview";
import { FlagBanner } from "../components/FlagBanner";
import { LoadingIndicator, MessageBanner } from "../components/ui";
import { api, type Fact, type ProfileField, type Run } from "../lib/api";
import { countryName, formatDate } from "../lib/format";
import { hostOf, safeHttpUrl, websiteUrl } from "../lib/safeUrl";
import { useAssessment } from "../lib/useAssessment";
import { hasProfile, useRunCard } from "../lib/useRunCard";
import { useTitle } from "../lib/useTitle";
import { AssessmentSection } from "./AssessmentSection";
import { BuyerContextForm } from "./BuyerContextForm";
import { NotFoundPage } from "./Simple";
import { WorkspacePage } from "./WorkspacePage";

/** The workspace, with the supplier card beside it when a card is open (route /profiles/:profileId). */
export function WorkspaceShell() {
  const open = useMatch("/profiles/:profileId") !== null;
  return (
    <div className={open ? "app app-open" : "app"}>
      <div className="workspace">
        <WorkspacePage />
      </div>
      <Outlet />
    </div>
  );
}

/** The one 409 the server answers with this message only: a review while the run has not finished. */
const IN_PROGRESS = "The run is still in progress.";

const lastRefresh = (run: Run): string => run.finished_at ?? run.started_at ?? run.created_at;

export function SupplierCardPanel() {
  const { t, i18n } = useTranslation();
  const { profileId = "" } = useParams();
  const navigate = useNavigate();
  const language = i18n.language === "fr" ? "fr" : "en";
  const { load, run, data, retry, applyFact, refreshRun } = useRunCard(profileId, language);
  const heading = useRef<HTMLHeadingElement>(null);
  const focused = useRef(false);
  // The element that opened the card, to give the focus back to it when the card closes.
  const [opener] = useState<Element | null>(() => document.activeElement);

  useTitle(run?.supplier_name ? `${run.supplier_name} · ${t("card.kicker")}` : t("card.kicker"));

  const close = useCallback(() => {
    navigate("/workspace");
    window.setTimeout(() => {
      const target =
        opener instanceof HTMLElement && opener.isConnected && opener !== document.body
          ? opener
          : document.querySelector<HTMLElement>(`a[data-run-id="${CSS.escape(profileId)}"]`);
      (target ?? document.getElementById("content"))?.focus();
    }, 0);
  }, [navigate, opener, profileId]);

  // When the card has loaded, focus moves to the supplier name.
  useEffect(() => {
    if (load === "ready" && !focused.current) {
      focused.current = true;
      heading.current?.focus();
    }
  }, [load]);

  const name = run?.supplier_name ?? t("workspace.nameHidden");
  return (
    <aside
      className="panel"
      id="panel"
      role="dialog"
      aria-modal="false"
      aria-label={load === "ready" && run ? undefined : t("card.kicker")}
      aria-labelledby={load === "ready" && run ? "card-name" : undefined}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !event.defaultPrevented) {
          event.preventDefault();
          close();
        }
      }}
    >
      <div className="card-bar">
        <span className="kicker">{t("card.kicker")}</span>
        <button type="button" className="btn btn-text" onClick={close}>
          {t("card.close")}
          <span className="vh"> {t("card.closeKey")}</span>
        </button>
      </div>
      {load === "loading" ? <LoadingIndicator /> : null}
      {load === "not_found" ? <NotFoundPage /> : null}
      {load === "error" ? (
        <div className="card-state">
          <MessageBanner kind="error">
            <p>{t("card.loadError")}</p>
            <p>
              <button type="button" className="btn btn-secondary" onClick={retry}>
                {t("common.retry")}
              </button>
            </p>
          </MessageBanner>
        </div>
      ) : null}
      {load === "ready" && run && !data ? (
        <div className="card-state">
          <h1 id="card-name" ref={heading} tabIndex={-1} className="card-name">
            {name}
          </h1>
          <MessageBanner kind="note">
            <p>
              {run.status === "queued" || run.status === "running" || run.status === "paused"
                ? t("card.inProgress")
                : t("card.noProfile", { status: t(`workspace.statuses.${run.status}`) })}
            </p>
            <p>
              <Link to={`/profiles/${run.id}/run`}>{t("card.openProgress")}</Link>
            </p>
          </MessageBanner>
          {run.status === "queued" || run.status === "running" || run.status === "paused" ? (
            <DownloadPdf runId={run.id} unavailableReason={t("pdf.unavailableInProgress")} />
          ) : null}
        </div>
      ) : null}
      {load === "ready" && run && data ? (
        <CardBody
          run={run}
          facts={data.facts}
          definition={data.definition}
          heading={heading}
          applyFact={applyFact}
          refreshRun={refreshRun}
          reload={retry}
        />
      ) : null}
    </aside>
  );
}

type Definition = NonNullable<ReturnType<typeof useRunCard>["data"]>["definition"];

function CardBody({
  run,
  facts,
  definition,
  heading,
  applyFact,
  refreshRun,
  reload,
}: {
  run: Run;
  facts: Fact[];
  definition: Definition;
  heading: RefObject<HTMLHeadingElement | null>;
  applyFact: (fact: Fact) => void;
  refreshRun: () => Promise<void>;
  reload: () => void;
}) {
  const { t, i18n } = useTranslation();
  const lockedId = useId();
  const [inProgress, setInProgress] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const assessment = useAssessment(run.id, hasProfile(run));
  // The buyer context form takes the place of the card body, as in mock-up 05-buyer-context-form.
  const [editingContext, setEditingContext] = useState(false);
  const contextButton = useRef<HTMLButtonElement>(null);
  const closeContext = useCallback(() => {
    setEditingContext(false);
    window.setTimeout(() => {
      (contextButton.current ?? document.getElementById("ctx"))?.focus();
    }, 0);
  }, []);
  const proposedLeft = run.proposed_facts;
  const countText = (count: number): string =>
    count === 0 ? t("card.review.countNone") : t("card.review.count", { count });

  const submit = useCallback(
    async (fact: Fact, label: string, body: ReviewBody): Promise<ReviewOutcome> => {
      const result = await api.reviewFact(fact.id, { ...body, version: fact.version });
      if (result.ok) {
        applyFact(result.data);
        const left = facts.filter(
          (item) => item.status === "proposed" && item.id !== fact.id,
        ).length;
        const said = t(
          body.status === "approved"
            ? "card.review.announceApproved"
            : "card.review.announceCorrected",
          { field: label },
        );
        setAnnouncement(`${said} ${countText(left)}`);
        void refreshRun();
        return { kind: "saved", fact: result.data };
      }
      if (result.kind === "conflict") {
        const current = result.current as Fact | undefined;
        if (current && typeof current === "object" && "version" in current) {
          applyFact(current);
          void refreshRun();
          return { kind: "conflict", current };
        }
        if (result.detail === IN_PROGRESS) {
          setInProgress(true);
          return { kind: "in_progress" };
        }
        return { kind: "rejected" };
      }
      if (result.kind === "unauthorized") return { kind: "signed_out" };
      if (result.kind === "not_found") return { kind: "gone" };
      if (result.kind === "validation") return { kind: "invalid" };
      return { kind: "error" };
    },
    [applyFact, refreshRun, facts, t],
  );
  const review: ReviewControls = useMemo(
    () => ({
      lockedReason: inProgress ? t("card.review.locked") : null,
      lockedId,
      submit,
      reload,
    }),
    [inProgress, lockedId, reload, submit, t],
  );
  const nextProposed = facts.find((item) => item.status === "proposed");
  const byField = new Map(facts.map((fact) => [fact.field, fact]));
  const uncovered = new Set(run.uncovered_sections);
  const partial = run.status === "partial";
  const sectionLabel = (id: string): string =>
    id === "recommendations"
      ? t("card.recommendations")
      : (definition.sections.find((section) => section.id === id)?.label ?? id);
  const site = websiteUrl(run.supplier_website);
  const figures = definition.sections.flatMap((section) =>
    section.fields
      .filter((field) => field.kind === "fact" && field.key_figure)
      .map((field) => ({ field, covered: !uncovered.has(section.id) || byField.has(field.id) })),
  );
  if (!hasProfile(run)) return null;

  return (
    <>
      <div className="card-head">
        <h1 className="card-name" id="card-name" ref={heading} tabIndex={-1}>
          {run.supplier_name ?? t("workspace.nameHidden")}
        </h1>
        <dl className="card-meta">
          <div>
            <dt>{t("card.website")}</dt>
            <dd>
              {site ? (
                <ExternalLink href={site}>{hostOf(site)}</ExternalLink>
              ) : (
                (run.supplier_website ?? t("identity.notGiven"))
              )}
            </dd>
          </div>
          <div>
            <dt>{t("card.country")}</dt>
            <dd>
              {run.supplier_country
                ? countryName(run.supplier_country, i18n.language)
                : t("identity.notGiven")}
            </dd>
          </div>
          <div>
            <dt>{t("card.sector")}</dt>
            <dd>{run.supplier_sector ?? t("identity.notGiven")}</dd>
          </div>
          <div>
            <dt>{t("card.lastRefresh")}</dt>
            <dd>{formatDate(lastRefresh(run), i18n.language)}</dd>
          </div>
          {/* The place of "Source content deletion" (mock-up 05-supplier-card-flags): #45 fills it. */}
        </dl>
        {figures.length > 0 ? <KeyFigures figures={figures} byField={byField} /> : null}
        <div className="card-count">
          <strong>{countText(proposedLeft)}</strong>
          {nextProposed ? (
            <button
              type="button"
              className="btn btn-text"
              onClick={() => document.getElementById(`fact-${nextProposed.id}`)?.focus()}
            >
              {t("card.review.nextProposed")}
            </button>
          ) : null}
        </div>
        <DownloadPdf runId={run.id} />
        <p className="vh" role="status">
          {announcement}
        </p>
      </div>
      {editingContext ? (
        <BuyerContextForm
          runId={run.id}
          stored={assessment.inputs?.buyer_context ?? null}
          onSaved={(saved) => {
            void assessment.reloadInputs();
            void assessment.reload();
            setAnnouncement(t("context.savedAnnounce", { version: saved.version }));
            closeContext();
          }}
          onCancel={closeContext}
          onConflict={() => void assessment.reloadInputs()}
        />
      ) : (
        <div className="card-body">
          {inProgress ? (
            <div id={lockedId}>
              <MessageBanner kind="error">
                <p>{t("card.review.locked")}</p>
              </MessageBanner>
            </div>
          ) : null}
          {run.identity_to_verify || partial ? (
            <div className="flags">
              {run.identity_to_verify ? (
                <FlagBanner label={t("card.identityToVerify")} live="none">
                  <p>
                    {t("card.identityToVerifyBody", {
                      name: run.supplier_name ?? t("workspace.nameHidden"),
                    })}
                  </p>
                </FlagBanner>
              ) : null}
              {partial ? (
                <FlagBanner label={t("card.partial")} live="none">
                  <p>
                    {t("card.partialBody", {
                      sections: run.uncovered_sections.map(sectionLabel).join(", "),
                    })}
                  </p>
                </FlagBanner>
              ) : null}
            </div>
          ) : null}

          {definition.sections.map((section) => {
            const fields = section.fields.filter((field) => field.kind === "fact");
            if (fields.length === 0) return null;
            const headingId = `section-${section.id}`;
            const sectionUncovered = uncovered.has(section.id);
            const none = !fields.some((field) => byField.has(field.id));
            return (
              <section className="section" key={section.id} aria-labelledby={headingId}>
                <h2 className="section-title" id={headingId}>
                  {section.label}
                  {sectionUncovered && none ? null : (
                    <span className="count">{t("card.fields", { count: fields.length })}</span>
                  )}
                </h2>
                {sectionUncovered && none ? (
                  <p className="not-covered">{t("card.notCoveredSection")}</p>
                ) : (
                  <FactList label={section.label}>
                    {(nav) =>
                      fields.map((field, index) => (
                        <FactRow
                          key={field.id}
                          label={field.label}
                          fact={byField.get(field.id) ?? null}
                          notCovered={sectionUncovered && !byField.has(field.id)}
                          concernsPeople={field.concerns_people}
                          certification={field.certification}
                          nav={nav(index)}
                          review={review}
                        />
                      ))
                    }
                  </FactList>
                )}
              </section>
            );
          })}

          <AssessmentSection
            run={run}
            facts={facts}
            definition={definition}
            state={assessment}
            onEditContext={() => setEditingContext(true)}
            contextButton={contextButton}
            announce={setAnnouncement}
          />
        </div>
      )}
    </>
  );
}

type Figure = { field: ProfileField; covered: boolean };

/** The key figures: a ruled line of selected facts, each with its status and its source chip. */
function KeyFigures({ figures, byField }: { figures: Figure[]; byField: Map<string, Fact> }) {
  const { t } = useTranslation();
  const [openId, setOpenId] = useState<string | null>(null);
  const chips = useRef(new Map<string, HTMLButtonElement>());
  const noteHeading = useRef<HTMLHeadingElement>(null);
  const last = useRef<string | null>(null);

  useEffect(() => {
    if (openId) {
      last.current = openId;
      noteHeading.current?.focus();
    } else if (last.current) {
      chips.current.get(last.current)?.focus();
      last.current = null;
    }
  }, [openId]);

  const open = figures.find(({ field }) => field.id === openId)?.field ?? null;
  const openFact = open ? byField.get(open.id) : undefined;
  return (
    <>
      <h2 className="vh">{t("card.keyFigures")}</h2>
      <dl className="kf" aria-label={t("card.keyFiguresHelp")}>
        {figures.map(({ field, covered }) => {
          const fact = byField.get(field.id);
          const evidence = fact && fact.status !== "not_found" ? fact : null;
          const noteId = `kf-note-${field.id}`;
          const verify = field.certification
            ? (safeHttpUrl(fact?.verification_url ?? null) ?? IAF_CERTSEARCH_URL)
            : null;
          return (
            <div key={field.id}>
              <dt>{field.label}</dt>
              <dd>
                {!covered ? (
                  <span className="v sm">
                    <span className="not-covered-field">{t("card.notCoveredField")}</span>
                  </span>
                ) : evidence ? (
                  <>
                    <span className={(evidence.value ?? "").length > 24 ? "v sm" : "v"}>
                      <Redacted text={evidence.value ?? ""} />
                    </span>
                    <span className="sub">
                      <StatusBadge
                        status={evidence.status as "proposed" | "approved" | "corrected"}
                      />
                    </span>
                    {evidence.quote ? (
                      <SourceChip
                        fact={evidence}
                        compact
                        noteId={noteId}
                        open={openId === field.id}
                        onToggle={() => setOpenId(openId === field.id ? null : field.id)}
                        chipRef={(node) => {
                          if (node) chips.current.set(field.id, node);
                          else chips.current.delete(field.id);
                        }}
                      />
                    ) : null}
                  </>
                ) : (
                  <span className="v sm">
                    <span className="missing">{t("card.noEvidence")}</span>
                  </span>
                )}
                {verify ? (
                  <span className="sub">
                    <ExternalLink href={verify}>{t("card.verifyIaf")}</ExternalLink>
                  </span>
                ) : null}
              </dd>
            </div>
          );
        })}
      </dl>
      {open && openFact?.quote ? (
        <QuoteBlock
          band
          fact={openFact}
          fieldLabel={open.label}
          noteId={`kf-note-${open.id}`}
          onClose={() => setOpenId(null)}
          headingRef={noteHeading}
        />
      ) : null}
    </>
  );
}

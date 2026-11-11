// The supplier card (spec F5, F3 display rules; mock-up 05-supplier-card-tearsheet, #163): a full page in
// the tearsheet style at /profiles/:profileId. Masthead, key figures, header details, the assessment (#37),
// recent events, then the profile as ruled ledgers (one row per fact field of the profile definition; a
// member can approve or correct each, #36), the buyer's inputs and the numbered sources. Every shown fact
// value carries the number of its source; the quote opens under the value. The deletion date (#45) is not
// here.
import {
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useNavigate, useParams } from "react-router";
import { DownloadPdf } from "../components/DownloadPdf";
import {
  ExternalLink,
  FactList,
  FactRow,
  IAF_CERTSEARCH_URL,
  Redacted,
  SourceTypeLabel,
  StatusBadge,
} from "../components/evidence";
import type { ReviewBody, ReviewControls, ReviewOutcome } from "../components/FactReview";
import { FlagBanner } from "../components/FlagBanner";
import { NotePanel, NoteRef, NotesProvider } from "../components/notes";
import { LoadingIndicator, MessageBanner } from "../components/ui";
import { type AssessmentStatement, api, type Fact, type ProfileField, type Run } from "../lib/api";
import { countryName, formatDate } from "../lib/format";
import {
  buildNoteIndex,
  formatEventDate,
  readEventDate,
  type SourceEntry,
  sortTimeline,
  type TimelineEntry,
} from "../lib/notes";
import { hostOf, safeHttpUrl, websiteUrl } from "../lib/safeUrl";
import { useAssessment } from "../lib/useAssessment";
import { hasProfile, useRunCard } from "../lib/useRunCard";
import { useTitle } from "../lib/useTitle";
import { AssessmentSection } from "./AssessmentSection";
import { BuyerContextForm } from "./BuyerContextForm";
import { NotFoundPage } from "./Simple";
import { WorkspacePage } from "./WorkspacePage";

/** The workspace list (route /workspace). The supplier card is its own page. */
export function WorkspaceShell() {
  return (
    <div className="app">
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

/** The order in which the assessment shows its statements, to number the sources as the page reads. */
const STATEMENT_ORDER: AssessmentStatement["kind"][] = [
  "strength",
  "threat",
  "opportunity",
  "evidence_gap",
  "weakness",
  "risk_indicator",
  "procurement_implication",
  "contract_approach",
  "volume_share",
  "next_action",
  "relationship_level",
  "procurement_priority",
  "fit",
];

export function SupplierCardPage() {
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

  // The card has its own look (the tearsheet theme); the page behind it takes its paper colour.
  useEffect(() => {
    document.body.classList.add("ts-page");
    return () => document.body.classList.remove("ts-page");
  }, []);

  const close = useCallback(() => {
    navigate("/workspace");
    // The list is loaded again: wait for the supplier link to be there, then give it the focus.
    let attempts = 0;
    const timer = window.setInterval(() => {
      attempts += 1;
      const target =
        opener instanceof HTMLElement && opener.isConnected && opener !== document.body
          ? opener
          : document.querySelector<HTMLElement>(`a[data-run-id="${CSS.escape(profileId)}"]`);
      if (target) {
        target.focus();
        window.clearInterval(timer);
      } else if (attempts >= 40) {
        document.getElementById("content")?.focus();
        window.clearInterval(timer);
      }
    }, 50);
  }, [navigate, opener, profileId]);

  // When the card has loaded, focus moves to the supplier name.
  useEffect(() => {
    if (load === "ready" && !focused.current) {
      focused.current = true;
      heading.current?.focus();
    }
  }, [load]);

  const name = run?.supplier_name ?? t("workspace.nameHidden");
  const closeButton = (
    <button type="button" className="link" onClick={close}>
      {t("card.close")}
      <span className="vh"> {t("card.closeKey")}</span>
    </button>
  );
  return (
    <article
      className="tearsheet"
      id="card"
      aria-label={load === "ready" && run ? undefined : t("card.kicker")}
      aria-labelledby={load === "ready" && run ? "card-name" : undefined}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !event.defaultPrevented) {
          event.preventDefault();
          close();
        }
      }}
    >
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
          <p>{closeButton}</p>
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
          <p>{closeButton}</p>
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
          closeButton={closeButton}
        />
      ) : null}
    </article>
  );
}

type Definition = NonNullable<ReturnType<typeof useRunCard>["data"]>["definition"];

type FieldOf = { field: ProfileField; sectionId: string };

function CardBody({
  run,
  facts,
  definition,
  heading,
  applyFact,
  refreshRun,
  reload,
  closeButton,
}: {
  run: Run;
  facts: Fact[];
  definition: Definition;
  heading: RefObject<HTMLHeadingElement | null>;
  applyFact: (fact: Fact) => void;
  refreshRun: () => Promise<void>;
  reload: () => void;
  closeButton: ReactNode;
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
  const byField = useMemo(() => new Map(facts.map((fact) => [fact.field, fact])), [facts]);
  const uncovered = new Set(run.uncovered_sections);
  const partial = run.status === "partial";
  const sectionLabel = (id: string): string =>
    id === "recommendations"
      ? t("card.recommendations")
      : (definition.sections.find((section) => section.id === id)?.label ?? id);
  const site = websiteUrl(run.supplier_website);

  const factFields: FieldOf[] = useMemo(
    () =>
      definition.sections.flatMap((section) =>
        section.fields
          .filter((field) => field.kind === "fact")
          .map((field) => ({ field, sectionId: section.id })),
      ),
    [definition],
  );
  const figures = factFields
    .filter(({ field }) => field.key_figure)
    .map(({ field, sectionId }) => ({
      field,
      covered: !uncovered.has(sectionId) || byField.has(field.id),
    }));
  const details = factFields
    .filter(({ field }) => field.header_detail)
    .map(({ field, sectionId }) => ({
      field,
      covered: !uncovered.has(sectionId) || byField.has(field.id),
    }));
  // Recent events: the facts of the timeline fields, newest dated first, undated last.
  const events = useMemo(
    () =>
      sortTimeline(
        factFields
          .filter(({ field }) => field.timeline)
          .flatMap(({ field }) => {
            const fact = byField.get(field.id);
            return fact && fact.status !== "not_found" && fact.value
              ? [{ item: { field, fact }, date: readEventDate(fact.value) }]
              : [];
          }),
      ),
    [factFields, byField],
  );

  // The sources are numbered in the order they first appear on the page.
  const index = useMemo(() => {
    const byId = new Map(facts.map((fact) => [fact.id, fact]));
    const items = [...(assessment.assessment?.items ?? [])].sort(
      (a, b) => STATEMENT_ORDER.indexOf(a.kind) - STATEMENT_ORDER.indexOf(b.kind),
    );
    return buildNoteIndex([
      ...factFields
        .filter(({ field }) => field.key_figure)
        .map(({ field }) => byField.get(field.id)),
      ...factFields
        .filter(({ field }) => field.header_detail)
        .map(({ field }) => byField.get(field.id)),
      ...items.flatMap((item) => item.cited_fact_ids.map((id) => byId.get(id))),
      ...events.map((entry) => entry.item.fact),
      ...factFields.map(({ field }) => byField.get(field.id)),
    ]);
  }, [facts, assessment.assessment, events, factFields, byField]);

  if (!hasProfile(run)) return null;
  const found = factFields.filter(({ field }) => {
    const fact = byField.get(field.id);
    return fact && fact.status !== "not_found";
  }).length;

  return (
    <NotesProvider index={index}>
      <header className="mast">
        <p className="kick">
          <span>{t("card.kicker")}</span>
          {run.supplier_sector ? <span>{run.supplier_sector}</span> : null}
          <span>
            {t("card.lastRefresh")} {formatDate(lastRefresh(run), i18n.language)}
          </span>
          <span className="num">
            {proposedLeft === 0
              ? t("card.review.countNone")
              : t("card.kickerProposed", { count: proposedLeft })}
          </span>
        </p>
        <h1 className="card-name" id="card-name" ref={heading} tabIndex={-1}>
          {run.supplier_name ?? t("workspace.nameHidden")}
        </h1>
        <p className="deck">
          <strong>{run.supplier_name ?? t("workspace.nameHidden")}</strong>
          {" · "}
          {run.supplier_country
            ? countryName(run.supplier_country, i18n.language)
            : t("identity.notGiven")}
          {" · "}
          {site ? (
            <ExternalLink href={site}>{hostOf(site)}</ExternalLink>
          ) : (
            (run.supplier_website ?? t("identity.notGiven"))
          )}
        </p>
        <div className="mast-actions">
          {nextProposed ? (
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => document.getElementById(`fact-${nextProposed.id}`)?.focus()}
            >
              {t("card.review.nextProposed")}
            </button>
          ) : null}
          <DownloadPdf runId={run.id} />
          {closeButton}
        </div>
        {/* The place of "Source content deletion" (mock-up 05-supplier-card-flags): #45 fills it. */}
        <p className="vh" role="status">
          {announcement}
        </p>
      </header>
      {figures.length > 0 ? <KeyFigures figures={figures} byField={byField} /> : null}
      {details.length > 0 ? <HeaderDetails details={details} byField={byField} /> : null}
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

          <AssessmentSection
            run={run}
            facts={facts}
            definition={definition}
            state={assessment}
            onEditContext={() => setEditingContext(true)}
            contextButton={contextButton}
            announce={setAnnouncement}
            between={
              <>
                {events.length > 0 ? <RecentEvents events={events} /> : null}
                <section className="section" id="profile" aria-labelledby="profile-h">
                  <h2 className="section-title" id="profile-h">
                    {t("card.profile")}
                    <span className="count">
                      {t("card.profileMeta", { count: factFields.length, found })}
                    </span>
                  </h2>
                  {definition.sections.map((section) => {
                    const fields = section.fields.filter((field) => field.kind === "fact");
                    if (fields.length === 0) return null;
                    const headingId = `section-${section.id}`;
                    const sectionUncovered = uncovered.has(section.id);
                    const none = !fields.some((field) => byField.has(field.id));
                    return (
                      <div className="ledger" key={section.id}>
                        <h3 className="ledger-title" id={headingId}>
                          {section.label}
                          {sectionUncovered && none ? null : (
                            <span className="count">
                              {t("card.fields", { count: fields.length })}
                            </span>
                          )}
                        </h3>
                        {sectionUncovered && none ? (
                          <p className="not-covered">{t("card.notCoveredSection")}</p>
                        ) : (
                          <FactList label={section.label}>
                            {(nav) =>
                              fields.map((field, position) => (
                                <FactRow
                                  key={field.id}
                                  label={field.label}
                                  fact={byField.get(field.id) ?? null}
                                  notCovered={sectionUncovered && !byField.has(field.id)}
                                  concernsPeople={field.concerns_people}
                                  certification={field.certification}
                                  nav={nav(position)}
                                  review={review}
                                />
                              ))
                            }
                          </FactList>
                        )}
                      </div>
                    );
                  })}
                </section>
              </>
            }
          />
          <SourcesSection sources={index.sources} />
        </div>
      )}
    </NotesProvider>
  );
}

type Figure = { field: ProfileField; covered: boolean };

/** The key figures: a ruled band of selected facts, each with its status and its note number. */
function KeyFigures({ figures, byField }: { figures: Figure[]; byField: Map<string, Fact> }) {
  const { t } = useTranslation();
  return (
    <>
      <h2 className="vh">{t("card.keyFigures")}</h2>
      <dl className="kf" aria-label={t("card.keyFiguresHelp")}>
        {figures.map(({ field, covered }) => {
          const fact = byField.get(field.id);
          const evidence = fact && fact.status !== "not_found" ? fact : null;
          const slot = `fig-${field.id}`;
          const verify = field.certification
            ? (safeHttpUrl(fact?.verification_url ?? null) ?? IAF_CERTSEARCH_URL)
            : null;
          return (
            <div key={field.id} className="fig">
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
                      <NoteRef fact={evidence} slot={slot} field={field.label} />
                    </span>
                    <span className="sub">
                      <StatusBadge
                        status={evidence.status as "proposed" | "approved" | "corrected"}
                      />
                    </span>
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
      {figures.map(({ field }) => {
        const fact = byField.get(field.id);
        return fact && fact.status !== "not_found" ? (
          <NotePanel key={field.id} fact={fact} slot={`fig-${field.id}`} field={field.label} />
        ) : null;
      })}
    </>
  );
}

/** Fields flagged `header_detail`, as label and value under the band (head office, group, ...). */
function HeaderDetails({ details, byField }: { details: Figure[]; byField: Map<string, Fact> }) {
  const { t } = useTranslation();
  return (
    <dl className="trio">
      {details.map(({ field, covered }) => {
        const fact = byField.get(field.id);
        const evidence = fact && fact.status !== "not_found" ? fact : null;
        const slot = `hd-${field.id}`;
        return (
          <div key={field.id}>
            <dt className="lab">{field.label}</dt>
            <dd>
              {!covered ? (
                <span className="not-covered-field">{t("card.notCoveredField")}</span>
              ) : evidence ? (
                <>
                  <Redacted text={evidence.value ?? ""} />
                  <NoteRef fact={evidence} slot={slot} field={field.label} />
                  {evidence ? <NotePanel fact={evidence} slot={slot} field={field.label} /> : null}
                </>
              ) : (
                <span className="missing">{t("card.noEvidence")}</span>
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

type EventItem = { field: ProfileField; fact: Fact };

/** Recent events: one line per fact of a timeline field; a date only when the value states one. */
function RecentEvents({ events }: { events: TimelineEntry<EventItem>[] }) {
  const { t, i18n } = useTranslation();
  return (
    <section className="section" id="events" aria-labelledby="events-h">
      <h2 className="section-title" id="events-h">
        {t("card.events")}
        <span className="count">{t("card.eventsMeta")}</span>
      </h2>
      <ol className="tl">
        {events.map(({ item, date }) => {
          const slot = `ev-${item.fact.id}`;
          return (
            <li key={item.fact.id}>
              <span className={date ? "d" : "d u"}>
                {date ? formatEventDate(date, i18n.language) : t("card.dateNotStated")}
              </span>
              <span>
                <span className="k">{item.field.label}</span>
                <Redacted text={item.fact.value ?? ""} />
                <NoteRef fact={item.fact} slot={slot} field={item.field.label} />
                <NotePanel fact={item.fact} slot={slot} field={item.field.label} />
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/** The numbered sources, each listed once with the quotes it supports. */
function SourcesSection({ sources }: { sources: SourceEntry[] }) {
  const { t, i18n } = useTranslation();
  if (sources.length === 0) return null;
  return (
    <section className="section" id="sources" aria-labelledby="sources-h">
      <h2 className="section-title" id="sources-h">
        {t("card.sources")}
        <span className="count">{t("card.sourcesMeta", { count: sources.length })}</span>
      </h2>
      <ol className="notes">
        {sources.map((source) => (
          <li key={source.key} id={`n${source.number}`}>
            <span className="t">{source.title}</span>
            {source.type ? <SourceTypeLabel type={source.type} /> : null}
            {source.url ? (
              <>
                {" · "}
                <ExternalLink href={source.url}>{hostOf(source.url) ?? source.url}</ExternalLink>
              </>
            ) : null}
            {source.fetchedAt ? <> · {formatDate(source.fetchedAt, i18n.language)}</> : null}
            {source.quotes.length > 0 ? (
              <ul>
                {source.quotes.map((quote) => (
                  <li key={quote}>
                    <q>
                      <Redacted text={quote} />
                    </q>
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

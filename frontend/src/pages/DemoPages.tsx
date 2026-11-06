// The public demo (#50; mock-ups 54-demo-*): pre-built, read-only profiles, browsed without an account.
// Everything here reads `/demo/...` through the API client; nothing can write, and every action that
// would call a model or change a profile is shown disabled with the reason, announced to screen readers.
// The card, the facts and the statements reuse the components of the member screens.
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Outlet, useMatch, useNavigate, useParams, useSearchParams } from "react-router";
import { useAuth } from "../auth/AuthContext";
import { DownloadPdf } from "../components/DownloadPdf";
import { ExternalLink, FactList, FactRow } from "../components/evidence";
import type { ReviewControls } from "../components/FactReview";
import { FlagBanner } from "../components/FlagBanner";
import { type StatementControls, StatementItem } from "../components/StatementItem";
import { Button, LoadingIndicator, MessageBanner } from "../components/ui";
import {
  api,
  type DemoProfile,
  type DemoProfileList,
  type DemoRun,
  type Language,
  type ProfileDefinition,
  type Run,
} from "../lib/api";
import { formatDate } from "../lib/format";
import { hostOf, safeHttpUrl, websiteUrl } from "../lib/safeUrl";
import { useTitle } from "../lib/useTitle";
import { ComparisonTable } from "./ComparisonPage";
import { NotFoundPage } from "./Simple";

const DEMO_LIST = "/demo/profiles";
const MAX_COMPARED = 10;
const RECOMMENDATION_KINDS = [
  "procurement_implication",
  "relationship_level",
  "contract_approach",
  "volume_share",
  "next_action",
  "procurement_priority",
] as const;
const ASSESSMENT_KINDS = [
  "strength",
  "weakness",
  "opportunity",
  "threat",
  "risk_indicator",
  "evidence_gap",
] as const;

const useLanguage = (): Language => (useTranslation().i18n.language === "fr" ? "fr" : "en");

/** A demo profile as the `Run` shape the shared components read: no usage, cost or user. */
export function demoRunAsRun(run: DemoRun): Run {
  return {
    id: run.id,
    identity_id: run.id,
    supplier_name: run.supplier_name,
    supplier_website: run.supplier_website,
    supplier_country: run.supplier_country,
    supplier_sector: run.supplier_sector,
    natural_person: run.natural_person,
    status: run.status,
    stage: "assessment",
    stop_requested: false,
    counts_against_quota: false,
    pause_dependency: null,
    pause_reason: null,
    error: null,
    profile_definition_hash: run.profile_definition_hash,
    prompt_set_hash: null,
    usage: {
      calls: 0,
      input_tokens: 0,
      output_tokens: 0,
      reasoning_tokens: 0,
      tool_calls: 0,
      cost: "0",
      roles: [],
    },
    excluded_sources: run.excluded_sources,
    identity_to_verify: run.identity_to_verify,
    grounding_failures: 0,
    invalid_items: 0,
    uncovered_sections: run.uncovered_sections,
    partial_explanation: run.partial_explanation,
    proposed_facts: run.proposed_facts,
    insufficient_sources_explanation: null,
    created_at: run.finished_at,
    started_at: null,
    finished_at: run.finished_at,
  };
}

/** The disclaimer band that sits under the top bar on every demo screen. */
function DemoBand({ disclaimer }: { disclaimer: string | null }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  return (
    <div className="demo-band" role="note" aria-label={t("demo.disclaimerLabel")}>
      <div className="in">
        <span className="micro">{t("demo.badge")}</span>
        <p className="demo-text">{disclaimer ?? t("demo.disclaimerLoading")}</p>
        {user ? null : <Link to="/login">{t("demo.signIn")}</Link>}
      </div>
    </div>
  );
}

type ListState = { kind: "loading" } | { kind: "ready"; list: DemoProfileList } | { kind: "error" };

function useDemoList(language: Language) {
  const [state, setState] = useState<ListState>({ kind: "loading" });
  const load = useCallback(async () => {
    setState({ kind: "loading" });
    const result = await api.getDemoProfiles(language);
    setState(result.ok ? { kind: "ready", list: result.data } : { kind: "error" });
  }, [language]);
  useEffect(() => {
    void load();
  }, [load]);
  return { state, retry: () => void load() };
}

/** The public landing: "Explore the demo" needs no account (mock-up 54-demo-entry). */
export function DemoLandingPage() {
  const { t } = useTranslation();
  const { state } = useDemoList(useLanguage());
  useTitle(t("demo.landingTitle"));
  return (
    <>
      <DemoBand disclaimer={state.kind === "ready" ? state.list.disclaimer : null} />
      <section className="hero" aria-labelledby="demo-landing-h">
        <span className="micro eyebrow">{t("app.name")}</span>
        <h1 id="demo-landing-h">{t("demo.landingTitle")}</h1>
        <p className="lede">{t("demo.landingLede")}</p>
        <p className="linkbox">
          <Link className="btn btn-primary" to={DEMO_LIST}>
            {t("demo.explore")}
          </Link>
          <Link className="btn btn-secondary" to="/login">
            {t("demo.signIn")}
          </Link>
        </p>
        <p className="meta">{t("demo.noAccount")}</p>
      </section>
      <ul className="three">
        <li>
          <strong>{t("demo.pointQuotedTitle")}</strong>
          <p>{t("demo.pointQuoted")}</p>
        </li>
        <li>
          <strong>{t("demo.pointGapsTitle")}</strong>
          <p>{t("demo.pointGaps")}</p>
        </li>
        <li>
          <strong>{t("demo.pointDecidesTitle")}</strong>
          <p>{t("demo.pointDecides")}</p>
        </li>
      </ul>
    </>
  );
}

/** The demo list with the supplier card beside it, as the workspace has. */
export function DemoShell() {
  const open = useMatch("/demo/profiles/:profileId") !== null;
  return (
    <div className={open ? "app app-open" : "app"}>
      <div className="workspace">
        <DemoListPage />
      </div>
      <Outlet />
    </div>
  );
}

function DemoListPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const language = useLanguage();
  const openId = useMatch("/demo/profiles/:profileId")?.params.profileId ?? null;
  const { state, retry } = useDemoList(language);
  const [selected, setSelected] = useState<string[]>([]);
  const newWhyId = useId();
  const compareWhyId = useId();
  useTitle(t("demo.listTitle"));

  const head = (
    <>
      <DemoBand disclaimer={state.kind === "ready" ? state.list.disclaimer : null} />
      <div className="ph">
        <div>
          <span className="micro eyebrow">{t("demo.badge")}</span>
          <h1>{t("demo.listTitle")}</h1>
          <p className="meta">{t("demo.listIntro")}</p>
        </div>
        <div className="ph-actions">
          <div>
            <button
              type="button"
              className="btn btn-primary"
              aria-disabled="true"
              aria-describedby={newWhyId}
            >
              {t("workspace.newProfile")}
            </button>
            <p className="reason" id={newWhyId}>
              {t("demo.newProfileWhy")}
            </p>
          </div>
        </div>
      </div>
    </>
  );
  if (state.kind === "loading") {
    return (
      <>
        {head}
        <LoadingIndicator />
      </>
    );
  }
  if (state.kind === "error") {
    return (
      <>
        {head}
        <MessageBanner kind="error">
          <p>{t("demo.loadError")}</p>
          <p>
            <button type="button" className="btn btn-secondary" onClick={retry}>
              {t("common.retry")}
            </button>
          </p>
        </MessageBanner>
      </>
    );
  }
  const profiles = state.list.items;
  const canCompare = selected.length >= 2;
  const atMaximum = selected.length >= MAX_COMPARED;
  const toggle = (id: string) =>
    setSelected((current) =>
      current.includes(id)
        ? current.filter((other) => other !== id)
        : current.length >= MAX_COMPARED
          ? current
          : [...current, id],
    );

  return (
    <>
      {head}
      {profiles.length === 0 ? (
        <section className="empty" aria-labelledby="demo-empty-h">
          <h2 id="demo-empty-h">{t("demo.emptyTitle")}</h2>
          <p>{t("demo.emptyBody")}</p>
        </section>
      ) : (
        <>
          <h2 className="vh">{t("workspace.listHeading")}</h2>
          <div className="toolbar">
            <span aria-live="polite">{t("workspace.selected", { count: selected.length })}</span>
            <button
              type="button"
              className="btn btn-secondary"
              aria-disabled={canCompare ? undefined : "true"}
              aria-describedby={canCompare ? undefined : compareWhyId}
              onClick={() => {
                if (canCompare) {
                  navigate(`/demo/compare?profiles=${selected.map(encodeURIComponent).join(",")}`);
                }
              }}
            >
              {t("workspace.compare")}
            </button>
            {canCompare ? null : (
              <span className="meta" id={compareWhyId}>
                {t("workspace.compareWhy")}
              </span>
            )}
            {atMaximum ? (
              <span className="meta" role="status">
                {t("compare.maximumReached", { maximum: MAX_COMPARED })}
              </span>
            ) : null}
          </div>
          <table className="tbl">
            <caption className="vh">{t("demo.caption")}</caption>
            <thead>
              <tr>
                <th scope="col" className="w-chk">
                  <span className="vh">{t("workspace.selectColumn")}</span>
                  {t("workspace.compareColumn")}
                </th>
                <th scope="col">{t("workspace.supplier")}</th>
                <th scope="col">{t("card.country")}</th>
                <th scope="col">{t("card.sector")}</th>
                <th scope="col">{t("card.lastRefresh")}</th>
                <th scope="col">{t("demo.flags")}</th>
              </tr>
            </thead>
            <tbody>
              {profiles.map((profile) => (
                <tr
                  key={profile.id}
                  className={
                    selected.includes(profile.id) || profile.id === openId ? "sel" : undefined
                  }
                >
                  <td data-label={t("workspace.compareColumn")}>
                    <label className="chk">
                      <input
                        type="checkbox"
                        checked={selected.includes(profile.id)}
                        disabled={atMaximum && !selected.includes(profile.id)}
                        onChange={() => toggle(profile.id)}
                      />
                      <span className="vh">
                        {t("workspace.selectFor", { name: profile.supplier_name })}
                      </span>
                    </label>
                  </td>
                  <td className="name" data-label={t("workspace.supplier")}>
                    <Link
                      to={`${DEMO_LIST}/${profile.id}`}
                      aria-current={profile.id === openId ? "true" : undefined}
                    >
                      {profile.supplier_name}
                    </Link>
                  </td>
                  <td data-label={t("card.country")}>
                    {profile.supplier_country ?? t("identity.notGiven")}
                  </td>
                  <td data-label={t("card.sector")}>
                    {profile.supplier_sector ?? t("identity.notGiven")}
                  </td>
                  <td data-label={t("card.lastRefresh")}>
                    {formatDate(profile.finished_at, i18n.language)}
                  </td>
                  <td data-label={t("demo.flags")}>
                    {[
                      t("compare.stillProposed", { count: profile.proposed_facts }),
                      profile.status === "partial" ? t("card.partial") : null,
                      profile.identity_to_verify ? t("card.identityToVerify") : null,
                      profile.excluded_sources.length > 0 ? t("run.excludedLabel") : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}

type CardState =
  | { kind: "loading" }
  | { kind: "ready"; profile: DemoProfile; definition: ProfileDefinition }
  | { kind: "not_found" }
  | { kind: "error" };

/** The supplier card of a demo profile (mock-up 54-demo-card): read-only, PDF still available. */
export function DemoCardPanel() {
  const { t, i18n } = useTranslation();
  const { profileId = "" } = useParams();
  const navigate = useNavigate();
  const language = useLanguage();
  const lockedId = useId();
  const [state, setState] = useState<CardState>({ kind: "loading" });

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    const [profile, definition] = await Promise.all([
      api.getDemoProfile(profileId, language),
      api.getDemoProfileDefinition(language),
    ]);
    if (!profile.ok)
      return setState({ kind: profile.kind === "not_found" ? "not_found" : "error" });
    if (!definition.ok) return setState({ kind: "error" });
    setState({ kind: "ready", profile: profile.data, definition: definition.data });
  }, [profileId, language]);
  useEffect(() => {
    void load();
  }, [load]);

  const reason = t("demo.readOnlyReason");
  const review: ReviewControls = useMemo(
    () => ({
      lockedReason: reason,
      lockedId,
      submit: async () => ({ kind: "rejected" }),
      reload: () => undefined,
    }),
    [reason, lockedId],
  );
  const statementControls: StatementControls = useMemo(
    () => ({
      lockedReason: reason,
      lockedId,
      submit: async () => ({ kind: "rejected" }),
      reload: () => undefined,
    }),
    [reason, lockedId],
  );
  useTitle(
    state.kind === "ready"
      ? `${state.profile.run.supplier_name} · ${t("demo.cardKicker")}`
      : t("demo.cardKicker"),
  );

  const close = () => navigate(DEMO_LIST);
  return (
    <aside
      className="panel"
      id="panel"
      role="dialog"
      aria-modal="false"
      aria-label={t("demo.cardKicker")}
      onKeyDown={(event) => {
        if (event.key === "Escape" && !event.defaultPrevented) {
          event.preventDefault();
          close();
        }
      }}
    >
      <div className="card-bar">
        <span className="kicker">{t("demo.cardKicker")}</span>
        <button type="button" className="btn btn-text" onClick={close}>
          {t("card.close")}
          <span className="vh"> {t("card.closeKey")}</span>
        </button>
      </div>
      {state.kind === "loading" ? <LoadingIndicator /> : null}
      {state.kind === "not_found" ? <NotFoundPage /> : null}
      {state.kind === "error" ? (
        <div className="card-state">
          <MessageBanner kind="error">
            <p>{t("card.loadError")}</p>
            <p>
              <button type="button" className="btn btn-secondary" onClick={() => void load()}>
                {t("common.retry")}
              </button>
            </p>
          </MessageBanner>
        </div>
      ) : null}
      {state.kind === "ready" ? (
        <>
          <div className="card-head">
            <h1 className="card-name" id="card-name">
              {state.profile.run.supplier_name}
            </h1>
            <DemoMeta run={state.profile.run} language={i18n.language} />
            <p className="card-count">
              <strong>
                {state.profile.run.proposed_facts === 0
                  ? t("card.review.countNone")
                  : t("card.review.count", { count: state.profile.run.proposed_facts })}
              </strong>
            </p>
            <DownloadPdf runId={state.profile.run.id} demo />
            <Button variant="secondary" disabled disabledReason={reason}>
              {t("demo.rerun")}
            </Button>
            <p className="reason" id={lockedId}>
              {reason}
            </p>
          </div>
          <div className="card-body">
            <DemoFlags run={state.profile.run} definition={state.definition} />
            <DemoFacts profile={state.profile} definition={state.definition} review={review} />
            <DemoAssessment
              profile={state.profile}
              definition={state.definition}
              controls={statementControls}
            />
            {state.profile.sources.length > 0 ? (
              <section className="section" aria-labelledby="demo-sources-h">
                <h2 className="section-title" id="demo-sources-h">
                  {t("demo.sources")}
                </h2>
                <ul>
                  {state.profile.sources.map((source) => {
                    const href = safeHttpUrl(source.url);
                    return (
                      <li key={source.url}>
                        {href ? (
                          <ExternalLink href={href}>{hostOf(href)}</ExternalLink>
                        ) : (
                          source.url
                        )}{" "}
                        <span className="meta">{formatDate(source.fetched_at, i18n.language)}</span>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ) : null}
          </div>
        </>
      ) : null}
    </aside>
  );
}

function DemoMeta({ run, language }: { run: DemoRun; language: string }) {
  const { t } = useTranslation();
  const site = websiteUrl(run.supplier_website);
  return (
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
        <dd>{run.supplier_country ?? t("identity.notGiven")}</dd>
      </div>
      <div>
        <dt>{t("card.sector")}</dt>
        <dd>{run.supplier_sector ?? t("identity.notGiven")}</dd>
      </div>
      <div>
        <dt>{t("card.lastRefresh")}</dt>
        <dd>{formatDate(run.finished_at, language)}</dd>
      </div>
    </dl>
  );
}

function DemoFlags({ run, definition }: { run: DemoRun; definition: ProfileDefinition }) {
  const { t } = useTranslation();
  const label = (id: string) =>
    id === "recommendations"
      ? t("card.recommendations")
      : (definition.sections.find((section) => section.id === id)?.label ?? id);
  if (!run.identity_to_verify && run.status !== "partial" && run.excluded_sources.length === 0) {
    return null;
  }
  return (
    <div className="flags">
      {run.identity_to_verify ? (
        <FlagBanner label={t("card.identityToVerify")} live="none">
          <p>{t("card.identityToVerifyBody", { name: run.supplier_name })}</p>
        </FlagBanner>
      ) : null}
      {run.status === "partial" ? (
        <FlagBanner label={t("card.partial")} live="none">
          <p>{t("card.partialBody", { sections: run.uncovered_sections.map(label).join(", ") })}</p>
        </FlagBanner>
      ) : null}
      {run.excluded_sources.length > 0 ? (
        <FlagBanner label={t("run.excludedLabel")} live="none">
          <p>{run.excluded_sources.map((source) => source.domain).join(", ")}</p>
        </FlagBanner>
      ) : null}
    </div>
  );
}

function DemoFacts({
  profile,
  definition,
  review,
}: {
  profile: DemoProfile;
  definition: ProfileDefinition;
  review: ReviewControls;
}) {
  const { t } = useTranslation();
  const byField = new Map(profile.facts.map((fact) => [fact.field, fact]));
  const uncovered = new Set(profile.run.uncovered_sections);
  return (
    <>
      {definition.sections.map((section) => {
        const fields = section.fields.filter((field) => field.kind === "fact");
        if (fields.length === 0) return null;
        const headingId = `demo-section-${section.id}`;
        const sectionUncovered = uncovered.has(section.id);
        const none = !fields.some((field) => byField.has(field.id));
        return (
          <section className="section" key={section.id} aria-labelledby={headingId}>
            <h2 className="section-title" id={headingId}>
              {section.label}
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
    </>
  );
}

function DemoAssessment({
  profile,
  definition,
  controls,
}: {
  profile: DemoProfile;
  definition: ProfileDefinition;
  controls: StatementControls;
}) {
  const { t } = useTranslation();
  const labels = new Map(
    definition.sections.flatMap((section) =>
      section.fields.map((field) => [field.id, field.label]),
    ),
  );
  const factLabel = new Map(
    profile.facts.map((fact) => [fact.id, labels.get(fact.field) ?? fact.field]),
  );
  const items = profile.assessment.items;
  const groups = [
    { id: "assessment", title: t("card.assessment"), kinds: ASSESSMENT_KINDS as readonly string[] },
    {
      id: "recommendations",
      title: t("card.recommendations"),
      kinds: RECOMMENDATION_KINDS as readonly string[],
    },
  ];
  return (
    <>
      {groups.map((group) => {
        const rows = items.filter((item) => group.kinds.includes(item.kind));
        return (
          <section className="section" key={group.id} aria-labelledby={`demo-${group.id}-h`}>
            <h2 className="section-title" id={`demo-${group.id}-h`}>
              {group.title}
            </h2>
            {rows.length === 0 ? (
              <p className="not-covered">{t("demo.noStatements")}</p>
            ) : (
              <ul className="statements">
                {rows.map((item) => (
                  <StatementItem
                    key={item.id}
                    item={item}
                    kindLabel={t(`assessment.kinds.${item.kind}`)}
                    cited={item.cited_fact_ids.map((id) => ({
                      id,
                      label: factLabel.get(id) ?? id,
                      correctedAfterDraft: false,
                    }))}
                    controls={controls}
                    byRules={item.provenance.provider === "rules"}
                  />
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </>
  );
}

type ComparisonState =
  | { kind: "loading" }
  | {
      kind: "ready";
      items: { run: Run; facts: DemoProfile["facts"] }[];
      definition: ProfileDefinition;
      disclaimer: string;
    }
  | { kind: "not_found" }
  | { kind: "range" }
  | { kind: "error" };

const DEMO_PATHS = {
  list: DEMO_LIST,
  card: (id: string) => `${DEMO_LIST}/${id}`,
  select: (ids: string[]) => `/demo/compare?profiles=${ids.map(encodeURIComponent).join(",")}`,
};

/** The comparison of two or more demo profiles (mock-up 54-demo-comparison): facts only. */
export function DemoComparisonPage() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const language = useLanguage();
  const ids = Array.from(
    new Set(
      (params.get("profiles") ?? "")
        .split(",")
        .map((id) => id.trim())
        .filter(Boolean),
    ),
  );
  const key = ids.join(",");
  const [state, setState] = useState<ComparisonState>({ kind: "loading" });
  useTitle(t("compare.title"));

  const load = useCallback(async () => {
    const wanted = key ? key.split(",") : [];
    if (wanted.length < 2) return setState({ kind: "range" });
    setState({ kind: "loading" });
    const [comparison, definition] = await Promise.all([
      api.getDemoComparison(wanted, language),
      api.getDemoProfileDefinition(language),
    ]);
    if (!comparison.ok) {
      if (comparison.kind === "not_found") return setState({ kind: "not_found" });
      if (comparison.kind === "validation") return setState({ kind: "range" });
      return setState({ kind: "error" });
    }
    if (!definition.ok) return setState({ kind: "error" });
    setState({
      kind: "ready",
      items: comparison.data.items.map((item) => ({
        run: demoRunAsRun(item.run),
        facts: item.facts,
      })),
      definition: definition.data,
      disclaimer: comparison.data.disclaimer,
    });
  }, [key, language]);
  useEffect(() => {
    void load();
  }, [load]);

  const band = <DemoBand disclaimer={state.kind === "ready" ? state.disclaimer : null} />;
  const title = <h1>{t("compare.title")}</h1>;
  if (state.kind === "loading") {
    return (
      <>
        {band}
        {title}
        <LoadingIndicator />
      </>
    );
  }
  if (state.kind === "not_found") {
    return (
      <>
        {band}
        <NotFoundPage />
      </>
    );
  }
  if (state.kind === "range" || state.kind === "error") {
    return (
      <>
        {band}
        {title}
        <MessageBanner kind={state.kind === "range" ? "note" : "error"}>
          <p>{state.kind === "range" ? t("compare.tooFew") : t("compare.loadError")}</p>
          <p>
            {state.kind === "error" ? (
              <button type="button" className="btn btn-secondary" onClick={() => void load()}>
                {t("common.retry")}
              </button>
            ) : (
              <Link to={DEMO_LIST}>{t("demo.backToList")}</Link>
            )}
          </p>
        </MessageBanner>
      </>
    );
  }
  return (
    <>
      {band}
      <ComparisonTable
        items={state.items}
        sections={state.definition.sections}
        organisationName={null}
        ids={ids}
        paths={DEMO_PATHS}
      />
    </>
  );
}

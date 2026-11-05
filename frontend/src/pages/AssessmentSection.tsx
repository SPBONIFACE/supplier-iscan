// The assessment section of the supplier card (#37; spec F8, Financial evidence guidance; mock-ups
// 05-assessment-*, 05-recommendations-*): statements grouped as SWOT, risk indicators, evidence gaps, the
// financial evidence guidance, the procurement recommendations, the fit against the member's criteria, and
// the buyer's own inputs. No aggregate score appears anywhere. For a natural-person business the whole
// section is replaced by neutral wording (owner decision D-073).
import { type RefObject, useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ExternalLink } from "../components/evidence";
import { FlagBanner } from "../components/FlagBanner";
import {
  type CitedFact,
  type StatementBody,
  type StatementControls,
  StatementItem,
  type StatementOutcome,
} from "../components/StatementItem";
import { Button, LoadingIndicator, MessageBanner } from "../components/ui";
import {
  type ApiFailure,
  type AssessmentStatement,
  api,
  type DraftingPart,
  type Fact,
  type FinancialGuidance,
  type ProfileDefinition,
  type Run,
} from "../lib/api";
import { formatDate, formatDateTime } from "../lib/format";
import type { useAssessment } from "../lib/useAssessment";
import { ContextSummary } from "./BuyerContextForm";
import { BuyerInputFields, CriteriaBox } from "./BuyerInputs";
import { NotFoundPage } from "./Simple";

const IN_PROGRESS = "The run is still in progress.";
const RECOMMENDATIONS: AssessmentStatement["kind"][] = [
  "procurement_implication",
  "relationship_level",
  "contract_approach",
  "volume_share",
  "next_action",
  "procurement_priority",
];

type AssessmentState = ReturnType<typeof useAssessment>;

type Props = {
  run: Run;
  facts: Fact[];
  definition: ProfileDefinition;
  state: AssessmentState;
  onEditContext: () => void;
  contextButton: RefObject<HTMLButtonElement | null>;
  announce: (message: string) => void;
};

/** Why a drafting request was refused, in plain words (409 and 403 on the two POST endpoints). */
function draftingProblem(result: ApiFailure): string {
  const detail = result.detail ?? "";
  if (result.kind === "refused" && result.reason === "spend_cap_reached") return "spendCap";
  if (/spend cap|monthly/i.test(detail)) return "spendCap";
  if (/natural-person/i.test(detail)) return "naturalPerson";
  if (/criteria/i.test(detail)) return "noCriteria";
  if (/cost budget/i.test(detail)) return "budget";
  if (/not been drafted/i.test(detail)) return "notDrafted";
  return result.kind === "conflict" ? "refused" : "unavailable";
}

export function AssessmentSection({
  run,
  facts,
  definition,
  state,
  onEditContext,
  contextButton,
  announce,
}: Props) {
  const { t, i18n } = useTranslation();
  const lockedId = useId();
  const [inProgress, setInProgress] = useState(false);
  const [problems, setProblems] = useState<Partial<Record<DraftingPart, string>>>({});
  const [asking, setAsking] = useState<DraftingPart | null>(null);
  const criteriaField = useRef<HTMLTextAreaElement>(null);
  const { assessment, inputs, applyStatement, reload } = state;

  // A drafting that ended is announced; the new statements appear in the lists.
  useEffect(() => {
    if (state.outcome.fit === "done") announce(t("assessment.fitDone"));
  }, [state.outcome.fit, announce, t]);
  useEffect(() => {
    if (state.outcome.recommendations === "done") announce(t("assessment.recoDone"));
  }, [state.outcome.recommendations, announce, t]);

  const labelOf = useMemo(() => {
    const labels = new Map<string, string>();
    for (const section of definition.sections) {
      for (const field of section.fields) labels.set(field.id, field.label);
    }
    return labels;
  }, [definition]);
  const factById = useMemo(() => new Map(facts.map((fact) => [fact.id, fact])), [facts]);
  const buyerFields = useMemo(
    () =>
      definition.sections.flatMap((section) =>
        section.fields
          .filter((field) => field.kind === "buyer")
          .map((field) => ({ id: field.id, label: field.label })),
      ),
    [definition],
  );

  const submit = useCallback(
    async (item: AssessmentStatement, body: StatementBody): Promise<StatementOutcome> => {
      const result = await api.reviewAssessmentStatement(item.id, {
        ...body,
        text: body.status === "corrected" ? body.text : undefined,
        version: item.version,
      });
      if (result.ok) {
        applyStatement(result.data);
        const name = t(`assessment.kinds.${item.kind}`);
        announce(
          t(
            body.status === "approved"
              ? "assessment.announceApproved"
              : body.status === "corrected"
                ? "assessment.announceCorrected"
                : "assessment.announceDeleted",
            { kind: name },
          ),
        );
        return { kind: "saved", statement: result.data };
      }
      if (result.kind === "conflict") {
        const current = result.current as AssessmentStatement | undefined;
        if (current && typeof current === "object" && "provenance" in current) {
          applyStatement(current);
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
    [applyStatement, announce, t],
  );
  const controls: StatementControls = useMemo(
    () => ({ lockedReason: inProgress ? t("assessment.locked") : null, lockedId, submit, reload }),
    [inProgress, lockedId, submit, reload, t],
  );

  async function draft(part: DraftingPart) {
    setProblems((was) => ({ ...was, [part]: undefined }));
    setAsking(part);
    const result = await (part === "fit"
      ? api.draftRunFit(run.id)
      : api.draftRunRecommendations(run.id));
    setAsking(null);
    if (result.ok) {
      state.startDrafting(part);
      announce(t(part === "fit" ? "assessment.fitQueued" : "assessment.recoQueued"));
    } else if (result.kind !== "unauthorized") {
      setProblems((was) => ({ ...was, [part]: draftingProblem(result) }));
    }
  }

  if (run.natural_person || assessment?.status === "not_assessed") {
    // Owner decision D-073: the whole section, recommendations and financial guidance included, is replaced.
    return (
      <>
        <section className="section" aria-labelledby="assessment-h">
          <h2 className="section-title" id="assessment-h" tabIndex={-1}>
            {t("card.assessment")}
          </h2>
          <p className="not-assessed">{t("card.naturalPerson")}</p>
        </section>
        {state.load === "ready" ? (
          <BuyerSection run={run} fields={buyerFields} state={state} announce={announce} />
        ) : null}
      </>
    );
  }
  if (state.load === "loading") return <LoadingIndicator />;
  if (state.load === "not_found") return <NotFoundPage />;
  if (state.load === "error" || !assessment) {
    return (
      <MessageBanner kind="error">
        <p>{t("assessment.loadError")}</p>
        <p>
          <button type="button" className="btn btn-secondary" onClick={reload}>
            {t("common.retry")}
          </button>
        </p>
      </MessageBanner>
    );
  }

  const items = assessment.items;
  const ofKind = (...kinds: AssessmentStatement["kind"][]) =>
    items.filter((item) => kinds.includes(item.kind));
  const isRules = (item: AssessmentStatement) => item.provenance.provider === "rules";
  const pendingCount = items.filter((item) => item.provenance.status === "ai_draft").length;
  const citedOf = (item: AssessmentStatement): CitedFact[] =>
    item.cited_fact_ids.flatMap((id) => {
      const fact = factById.get(id);
      if (!fact) return [];
      return [
        {
          id,
          label: labelOf.get(fact.field) ?? fact.field,
          correctedAfterDraft:
            fact.status === "corrected" &&
            !!fact.reviewed_at &&
            fact.reviewed_at > item.provenance.generated_at,
        },
      ];
    });

  const statement = (
    item: AssessmentStatement,
    extra: Partial<React.ComponentProps<typeof StatementItem>> = {},
  ) => (
    <StatementItem
      key={item.id}
      item={item}
      cited={citedOf(item)}
      controls={controls}
      byRules={isRules(item)}
      {...extra}
    />
  );
  const group = (title: string, list: AssessmentStatement[], key: string) =>
    list.length === 0 ? null : (
      <div key={key}>
        <h3 className="sub-title" tabIndex={-1}>
          {title}
        </h3>
        <ul className="stmts">{list.map((item) => statement(item))}</ul>
      </div>
    );

  const gaps = ofKind("evidence_gap").filter((item) => !isRules(item));
  const financial = ofKind("evidence_gap").filter(isRules);
  const guidance = assessment.financial_guidance;
  const partial = assessment.status === "partial";
  const recoItems = RECOMMENDATIONS.flatMap((kind) => ofKind(kind));
  const outdated = recoItems.some((item) => item.buyer_context_outdated);
  const context = inputs?.buyer_context ?? null;
  const criteria = inputs?.criteria ?? null;
  const hasCriteria = (criteria?.criteria.length ?? 0) > 0;
  const drafting = (part: DraftingPart) =>
    state.drafting.includes(part) || assessment.pending.includes(part);
  const budgetReason = partial ? t("assessment.problems.budget") : undefined;
  const fitItems = ofKind("fit");

  return (
    <>
      <section className="section" id="sec-assessment" aria-labelledby="assessment-h">
        <h2 className="section-title" id="assessment-h" tabIndex={-1}>
          {t("card.assessment")}
          {pendingCount > 0 ? (
            <span className="count">{t("assessment.pendingCount", { count: pendingCount })}</span>
          ) : null}
        </h2>
        <p className="section-lede">{t("assessment.lede")}</p>
        {inProgress ? (
          <div id={lockedId}>
            <MessageBanner kind="error">
              <p>{t("assessment.locked")}</p>
            </MessageBanner>
          </div>
        ) : null}
        {partial ? (
          <FlagBanner label={t("card.partial")} live="none">
            <p>{t("assessment.partialBody")}</p>
          </FlagBanner>
        ) : null}
        {assessment.status === "pending" ? (
          <MessageBanner kind="note">
            <p>{t("assessment.pending")}</p>
          </MessageBanner>
        ) : (
          <>
            {group(t("assessment.groups.strength"), ofKind("strength"), "s")}
            {group(t("assessment.groups.weakness"), ofKind("weakness"), "w")}
            {group(t("assessment.groups.opportunity"), ofKind("opportunity"), "o")}
            {group(t("assessment.groups.threat"), ofKind("threat"), "t")}
            {group(t("assessment.groups.risk_indicator"), ofKind("risk_indicator"), "r")}
            {group(t("assessment.groups.evidence_gap"), gaps, "g")}
            {guidance || financial.length > 0 ? (
              <div>
                <h3 className="sub-title" tabIndex={-1}>
                  {t("assessment.groups.financial")}
                  <span className="meta">{t("assessment.fromRules")}</span>
                </h3>
                <ul className="stmts">
                  {financial.map((item) =>
                    statement(item, {
                      children: guidance ? <GuidanceDetails guidance={guidance} /> : null,
                    }),
                  )}
                  {financial.length === 0 && guidance ? (
                    <li className="stmt">
                      <GuidanceDetails guidance={guidance} />
                    </li>
                  ) : null}
                </ul>
              </div>
            ) : null}

            <h3 className="sub-title" tabIndex={-1} id="reco-h">
              {t("card.recommendations")}
              {recoItems.length > 0 ? (
                <span className="meta">
                  {t("assessment.pendingCount", {
                    count: recoItems.filter((item) => item.provenance.status === "ai_draft").length,
                  })}
                </span>
              ) : null}
            </h3>
            {outdated ? (
              <div className="flag stale" role="status">
                <span className="ml">{t("assessment.contextChanged")}</span>
                <p>
                  {assessment.buyer_context_version === null
                    ? t("assessment.contextChangedFirst")
                    : t("assessment.contextChangedBody", {
                        drafted: assessment.buyer_context_version,
                        current: assessment.current_buyer_context_version ?? "",
                      })}
                </p>
              </div>
            ) : null}
            {drafting("recommendations") ? (
              <div className="drafting" role="status">
                <strong>{t("assessment.drafting")}</strong>{" "}
                <span className="help">{t("assessment.draftingHelp")}</span>
                <span className="bar" aria-hidden="true">
                  <span />
                </span>
              </div>
            ) : (
              <>
                <div className="form-row">
                  <Button
                    variant={outdated ? "primary" : "secondary"}
                    onClick={() => void draft("recommendations")}
                    loading={asking === "recommendations"}
                    loadingLabel={t("assessment.asking")}
                    disabled={partial || inProgress}
                    disabledReason={budgetReason}
                    aria-describedby="redraft-help"
                  >
                    {t("assessment.redraftRecommendations")}
                  </Button>
                  <span className="help" id="redraft-help">
                    {t("assessment.redraftHelp")}
                  </span>
                </div>
                {state.outcome.recommendations === "nothing_new" ? (
                  <MessageBanner kind="note">
                    <p>{t("assessment.nothingNew")}</p>
                  </MessageBanner>
                ) : null}
              </>
            )}
            <DraftingProblem problem={problems.recommendations} />
            {context ? (
              <div className="ctx" id="ctx" tabIndex={-1}>
                <span className="kicker">{t("context.kicker")}</span>
                <ContextSummary context={context} />
                <p className="byline" style={{ marginTop: "var(--isc-space-2)" }}>
                  {t("context.saved", {
                    version: context.version,
                    who: context.updated_by_email ?? t("assessment.aMember"),
                    date: formatDateTime(context.updated_at, i18n.language),
                  })}
                </p>
                <div className="form-row">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={onEditContext}
                    ref={contextButton}
                  >
                    {t("context.edit")}
                  </button>
                </div>
              </div>
            ) : (
              <div className="invite" id="ctx" tabIndex={-1}>
                <strong>{t("context.none")}</strong> {t("context.noneBody")}
                <div className="form-row">
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={onEditContext}
                    ref={contextButton}
                  >
                    {t("context.add")}
                  </button>
                </div>
              </div>
            )}
            {recoItems.length > 0 ? (
              <ul className="stmts" style={{ marginTop: "var(--isc-space-4)" }}>
                {recoItems.map((item) =>
                  statement(item, {
                    kindLabel: t(`assessment.kinds.${item.kind}`),
                    redraftNote: outdated
                      ? item.provenance.status === "ai_draft"
                        ? "replaces"
                        : "keeps"
                      : null,
                    onRedraft: () => void draft("recommendations"),
                    redraftDisabled: partial || inProgress || drafting("recommendations"),
                  }),
                )}
              </ul>
            ) : (
              <p className="empty-fit">{t("assessment.noRecommendations")}</p>
            )}
          </>
        )}
      </section>

      {assessment.status === "pending" ? null : (
        <section className="section" id="sec-fit" aria-labelledby="fit-h">
          <h2 className="section-title" id="fit-h" tabIndex={-1}>
            {t("assessment.fitTitle")}
            {fitItems.length > 0 ? (
              <span className="count">
                {t("assessment.pendingCount", {
                  count: fitItems.filter((item) => item.provenance.status === "ai_draft").length,
                })}
              </span>
            ) : null}
          </h2>
          {hasCriteria ? null : (
            <p className="empty-fit">
              {t("assessment.fitEmpty")}{" "}
              <button
                type="button"
                className="btn btn-text"
                onClick={() => criteriaField.current?.focus()}
              >
                {t("assessment.goToCriteria")}
              </button>
            </p>
          )}
          <CriteriaBox
            runId={run.id}
            stored={criteria}
            onSaved={state.reloadInputs}
            announce={announce}
            fieldRef={criteriaField}
          />
          {drafting("fit") ? (
            <div className="drafting" role="status">
              <strong>{t("assessment.draftingFit")}</strong>{" "}
              <span className="help">{t("assessment.draftingHelp")}</span>
              <span className="bar" aria-hidden="true">
                <span />
              </span>
            </div>
          ) : (
            <div className="form-row">
              <Button
                variant={hasCriteria && fitItems.length === 0 ? "primary" : "secondary"}
                onClick={() => void draft("fit")}
                loading={asking === "fit"}
                loadingLabel={t("assessment.asking")}
                disabled={!hasCriteria || partial || inProgress}
                disabledReason={!hasCriteria ? t("assessment.saveCriteriaFirst") : budgetReason}
              >
                {fitItems.length > 0 ? t("assessment.redraftFit") : t("assessment.draftFit")}
              </Button>
              {hasCriteria ? <span className="help">{t("assessment.draftFitHelp")}</span> : null}
            </div>
          )}
          {state.outcome.fit === "nothing_new" ? (
            <MessageBanner kind="note">
              <p>{t("assessment.nothingNew")}</p>
            </MessageBanner>
          ) : null}
          <DraftingProblem problem={problems.fit} />
          {fitItems.length > 0 ? (
            <ul className="stmts">
              {fitItems.map((item) =>
                statement(item, {
                  onRedraft: () => void draft("fit"),
                  redraftDisabled: partial || inProgress || drafting("fit"),
                }),
              )}
            </ul>
          ) : null}
        </section>
      )}

      <BuyerSection run={run} fields={buyerFields} state={state} announce={announce} />
    </>
  );
}

function DraftingProblem({ problem }: { problem: string | undefined }) {
  const { t } = useTranslation();
  if (!problem) return null;
  return (
    <MessageBanner kind="error">
      <p>{t(`assessment.problems.${problem}`)}</p>
    </MessageBanner>
  );
}

function BuyerSection({
  run,
  fields,
  state,
  announce,
}: {
  run: Run;
  fields: { id: string; label: string }[];
  state: AssessmentState;
  announce: (message: string) => void;
}) {
  const { t } = useTranslation();
  if (fields.length === 0) return null;
  return (
    <section className="section" id="sec-buyer" aria-labelledby="buyer-h">
      <h2 className="section-title" id="buyer-h" tabIndex={-1}>
        {t("assessment.buyerTitle")}
      </h2>
      <p className="section-lede">{t("assessment.buyerLede")}</p>
      <BuyerInputFields
        runId={run.id}
        fields={fields}
        stored={state.inputs?.inputs ?? []}
        onSaved={state.reloadInputs}
        announce={announce}
      />
    </section>
  );
}

/** The financial evidence guidance of one entry: documents, access status, what is missing, the registry. */
function GuidanceDetails({ guidance }: { guidance: FinancialGuidance }) {
  const { t, i18n } = useTranslation();
  return (
    <div>
      {guidance.example_table ? (
        // Always visible: rows from the example table must never look like verified guidance.
        <FlagBanner label={t("assessment.fin.exampleLabel")} live="none">
          <p>{t("assessment.fin.exampleBody")}</p>
        </FlagBanner>
      ) : null}
      {guidance.configured ? (
        <table className="docs">
          <caption>{t("assessment.fin.caption", { year: guidance.financial_year })}</caption>
          <thead>
            <tr>
              <th scope="col">{t("assessment.fin.document")}</th>
              <th scope="col">{t("assessment.fin.entity")}</th>
              <th scope="col">{t("assessment.fin.access")}</th>
            </tr>
          </thead>
          <tbody>
            {guidance.documents.map((document) => (
              <tr key={`${document.scope}-${document.type}`}>
                <td data-label={t("assessment.fin.document")}>
                  {t(`assessment.fin.types.${document.type}`)}
                </td>
                <td data-label={t("assessment.fin.entity")}>
                  {t(`assessment.fin.scopes.${document.scope}`)}
                </td>
                <td data-label={t("assessment.fin.access")}>
                  <span className="access">
                    {t(`assessment.fin.accessStatus.${document.access}`)}
                  </span>
                  {document.registry_link ? (
                    <>
                      {" · "}
                      <ExternalLink href={document.registry_link}>
                        {t("assessment.fin.openRegistry")}
                      </ExternalLink>
                    </>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="stmt-text">{t("assessment.fin.notConfigured")}</p>
      )}
      <dl className="kv">
        {guidance.missing_evidence.length > 0 ? (
          <>
            <dt>{t("assessment.fin.missing")}</dt>
            <dd>
              {guidance.missing_evidence
                .map((value) => t(`assessment.fin.missingKinds.${value}`))
                .join("; ")}
            </dd>
          </>
        ) : null}
        {guidance.documents_to_request.length > 0 ? (
          <>
            <dt>{t("assessment.fin.request")}</dt>
            <dd>
              {guidance.documents_to_request
                .map((value) => t(`assessment.fin.requestKinds.${value}`))
                .join("; ")}
            </dd>
          </>
        ) : null}
        {guidance.registry_url ? (
          <>
            <dt>{t("assessment.fin.registry")}</dt>
            <dd>
              <ExternalLink href={guidance.registry_url}>
                {guidance.registry_name ?? guidance.registry_url}
              </ExternalLink>
              {" · "}
              {t("assessment.fin.neverBought")}
            </dd>
          </>
        ) : null}
        {guidance.last_checked ? (
          <>
            <dt>{t("assessment.fin.lastChecked")}</dt>
            <dd>{formatDate(guidance.last_checked, i18n.language)}</dd>
          </>
        ) : null}
      </dl>
    </div>
  );
}

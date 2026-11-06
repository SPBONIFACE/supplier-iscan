// The side-by-side comparison (spec F5; mock-ups 06-comparison-*): the facts of 2 to 4 profiles as columns,
// of 5 or more as a compact matrix, field by field. Facts only (owner decision D-073, 5 Nov 2026): no
// assessment, no score, no colour or order that suggests one supplier is better, and a value that is
// missing is never written as a weakness. Every value keeps its status and its source chip.
import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";
import {
  ExternalLink,
  IAF_CERTSEARCH_URL,
  QuoteBlock,
  Redacted,
  SourceChip,
  SourceTypeLabel,
  StatusBadge,
  useQuoteToggle,
} from "../components/evidence";
import { LoadingIndicator, MessageBanner } from "../components/ui";
import type { ComparisonRun, Fact, ProfileField, Run } from "../lib/api";
import { formatDate } from "../lib/format";
import { safeHttpUrl } from "../lib/safeUrl";
import { parseRunIds, useComparison } from "../lib/useComparison";
import { useTitle } from "../lib/useTitle";
import { NotFoundPage } from "./Simple";

/** From this many profiles on, the columns are narrower (mock-up 06-comparison-matrix). */
const MATRIX_FROM = 5;
const IN_PROGRESS = ["queued", "running", "paused"];

const lastRefresh = (run: Run): string => run.finished_at ?? run.started_at ?? run.created_at;
type BadgeStatus = Exclude<Fact["status"], "not_found">;

export function ComparisonPage() {
  const { t, i18n } = useTranslation();
  const [params] = useSearchParams();
  const language = i18n.language === "fr" ? "fr" : "en";
  const ids = parseRunIds(params.get("runs"));
  const { load, retry } = useComparison(ids, language);
  useTitle(t("compare.title"));

  if (load.kind === "loading") {
    return (
      <>
        <h1>{t("compare.title")}</h1>
        <LoadingIndicator />
      </>
    );
  }
  if (load.kind === "not_found") return <NotFoundPage />;
  if (load.kind === "range") {
    return (
      <>
        <h1>{t("compare.title")}</h1>
        <MessageBanner kind="note">
          <p>
            {ids.length < 2 || load.maximum === null
              ? t("compare.tooFew")
              : t("compare.range", { maximum: load.maximum })}
          </p>
          <p>
            <Link to="/workspace">{t("compare.backToWorkspace")}</Link>
          </p>
        </MessageBanner>
      </>
    );
  }
  if (load.kind === "error") {
    return (
      <>
        <h1>{t("compare.title")}</h1>
        <MessageBanner kind="error">
          <p>{t("compare.loadError")}</p>
          <p>
            <button type="button" className="btn btn-secondary" onClick={retry}>
              {t("common.retry")}
            </button>
          </p>
        </MessageBanner>
      </>
    );
  }
  return (
    <ComparisonTable
      items={load.data.items}
      sections={load.data.definition.sections}
      organisationName={load.data.organisation?.name ?? null}
      ids={ids}
    />
  );
}

type Section = { id: string; label: string; fields: ProfileField[] };

/** Where the demo's comparison links lead: its own list, cards and selection (#50). */
export type ComparisonPaths = {
  list: string;
  card: (id: string) => string;
  select: (ids: string[]) => string;
};

const MEMBER_PATHS: ComparisonPaths = {
  list: "/workspace",
  card: (id) => `/profiles/${id}`,
  select: (ids) => `/compare?runs=${ids.map(encodeURIComponent).join(",")}`,
};

export function ComparisonTable({
  items,
  sections,
  organisationName,
  ids,
  paths = MEMBER_PATHS,
}: {
  items: ComparisonRun[];
  sections: Section[];
  organisationName: string | null;
  ids: string[];
  paths?: ComparisonPaths;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const base = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const table = useRef<HTMLTableElement>(null);
  const [active, setActive] = useState({ row: 0, column: 0 });
  const compact = items.length >= MATRIX_FROM;
  const shown = sections
    .map((section) => ({ ...section, fields: section.fields.filter((f) => f.kind === "fact") }))
    .filter((section) => section.fields.length > 0);
  const names = items.map((item) => item.run.supplier_name ?? t("workspace.nameHidden"));
  const labelWidth = compact ? 168 : 200;
  const columnWidth = compact ? 176 : 220;

  // The page title takes the focus when the screen opens or a column is removed.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    heading.current?.focus();
  }, [ids.length]);

  const remove = (id: string) => {
    const left = ids.filter((other) => other !== id);
    navigate(paths.select(left), { replace: true });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTableElement>) => {
    const cell = event.target as HTMLElement;
    if (cell.getAttribute("role") !== "gridcell" || !table.current) return;
    const rows = Array.from(table.current.querySelectorAll<HTMLTableRowElement>("tr[data-row]"));
    const row = rows.findIndex((candidate) => candidate === cell.parentElement);
    const cells = (index: number) =>
      Array.from(rows[index]?.querySelectorAll<HTMLElement>('[role="gridcell"]') ?? []);
    const column = cells(row).indexOf(cell);
    if (row < 0 || column < 0) return;
    const starts = rows.flatMap((candidate, index) => (candidate.dataset.first ? [index] : []));
    const last = rows.length - 1;
    const width = cells(row).length - 1;
    let target: [number, number] | null = null;
    switch (event.key) {
      case "ArrowRight":
        target = [row, Math.min(column + 1, width)];
        break;
      case "ArrowLeft":
        target = [row, Math.max(column - 1, 0)];
        break;
      case "ArrowDown":
        target = [Math.min(row + 1, last), column];
        break;
      case "ArrowUp":
        target = [Math.max(row - 1, 0), column];
        break;
      case "Home":
        target = event.ctrlKey ? [0, 0] : [row, 0];
        break;
      case "End":
        target = event.ctrlKey ? [last, width] : [row, width];
        break;
      case "PageDown":
        target = [starts.find((index) => index > row) ?? last, column];
        break;
      case "PageUp":
        target = [[...starts].reverse().find((index) => index < row) ?? 0, column];
        break;
      case "Enter": {
        const chip = cell.querySelector<HTMLElement>("button.chip");
        if (chip) {
          event.preventDefault();
          chip.focus();
        }
        return;
      }
      default:
        return;
    }
    event.preventDefault();
    const next = cells(target[0])[target[1]];
    next?.focus();
    next?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  };

  let rowNumber = -1;
  return (
    <>
      <div className="ph">
        <div>
          {organisationName ? (
            <span className="micro eyebrow">
              {t("compare.eyebrow", { organisation: organisationName })}
            </span>
          ) : null}
          <h1 ref={heading} tabIndex={-1}>
            {t("compare.heading", { count: items.length })}
          </h1>
          <p className="sec">{names.join(", ")}</p>
          <p className="meta">{t(compact ? "compare.introMatrix" : "compare.intro")}</p>
        </div>
        <div className="ph-actions">
          <Link className="btn btn-secondary" to={paths.list}>
            {t("compare.changeSelection")}
          </Link>
        </div>
      </div>

      <div className="cmp-legend">
        <span>
          <span className="badge badge--pending">{t("card.status.proposed")}</span>{" "}
          {t("compare.legendProposed")}
        </span>
        <span>
          <span className="badge badge--decided">{t("card.status.approved")}</span>{" "}
          {t("compare.legendApproved")}
        </span>
        <span>
          <span className="missing">{t("card.noEvidence")}</span>
        </span>
        <span>{t("compare.legendChip")}</span>
      </div>

      <section className="cmp-wrap" aria-label={t("compare.scrollRegion")} tabIndex={-1}>
        <table
          ref={table}
          className={compact ? "cmp matrix" : "cmp"}
          // The grid pattern of mock-up #6: one tab stop, arrow keys between cells.
          // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: specified by the approved mock-up
          role="grid"
          aria-label={t("compare.tableLabel", { count: items.length })}
          style={{ minWidth: labelWidth + columnWidth * items.length }}
          onKeyDown={onKeyDown}
        >
          <colgroup>
            <col style={{ width: labelWidth }} />
            {items.map((item) => (
              <col key={item.run.id} style={{ width: columnWidth }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th scope="col" className="lab">
                {t("compare.field")}
              </th>
              {items.map((item, index) => (
                <th scope="col" key={item.run.id} id={`${base}-c-${index}`}>
                  <ColumnHead
                    run={item.run}
                    name={names[index] ?? ""}
                    compact={compact}
                    cardPath={paths.card(item.run.id)}
                    onRemove={() => remove(item.run.id)}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((section) => (
              <SectionRows key={section.id} label={section.label} span={items.length + 1}>
                {section.fields.map((field, position) => {
                  rowNumber += 1;
                  const row = rowNumber;
                  return (
                    <tr
                      key={field.id}
                      data-row={row}
                      data-first={position === 0 ? "true" : undefined}
                      className={active.row === row ? "row-active" : undefined}
                    >
                      <th scope="row" className="lab" id={`${base}-r-${field.id}`}>
                        {field.label}
                        {field.concerns_people ? (
                          <span className="f-hint">{t("card.aboutPeople")}</span>
                        ) : null}
                      </th>
                      {items.map((item, column) => (
                        <Cell
                          key={item.run.id}
                          item={item}
                          field={field}
                          sectionId={section.id}
                          compact={compact}
                          headers={`${base}-c-${column} ${base}-r-${field.id}`}
                          tabIndex={active.row === row && active.column === column ? 0 : -1}
                          onFocus={() => setActive({ row, column })}
                        />
                      ))}
                    </tr>
                  );
                })}
              </SectionRows>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

function SectionRows({
  label,
  span,
  children,
}: {
  label: string;
  span: number;
  children: React.ReactNode;
}) {
  return (
    <>
      <tr className="secrow">
        <th colSpan={span} scope="colgroup">
          <span className="stick">
            <h3>{label}</h3>
          </span>
        </th>
      </tr>
      {children}
    </>
  );
}

function ColumnHead({
  run,
  name,
  compact,
  cardPath,
  onRemove,
}: {
  run: Run;
  name: string;
  compact: boolean;
  cardPath: string;
  onRemove: () => void;
}) {
  const { t, i18n } = useTranslation();
  const running = IN_PROGRESS.includes(run.status);
  const hasProfile = run.status === "completed" || run.status === "partial";
  const where = [run.supplier_country, compact ? null : run.supplier_sector].filter(Boolean);
  return (
    <div className="colhead">
      <h2>{name}</h2>
      {where.length > 0 ? <span className="meta">{where.join(" · ")}</span> : null}
      <span className="meta">
        {running
          ? t("compare.runInProgress")
          : !hasProfile
            ? t("compare.noProfile", { status: t(`workspace.statuses.${run.status}`) })
            : compact
              ? t("compare.stillProposed", { count: run.proposed_facts })
              : t("compare.refreshAndProposed", {
                  date: formatDate(lastRefresh(run), i18n.language),
                  count: run.proposed_facts,
                })}
      </span>
      {run.status === "partial" || run.identity_to_verify || run.excluded_sources.length > 0 ? (
        <div className="row">
          {run.status === "partial" ? <span className="flagtag">{t("card.partial")}</span> : null}
          {run.identity_to_verify ? (
            <span className="flagtag">{t("card.identityToVerify")}</span>
          ) : null}
          {run.excluded_sources.length > 0 ? (
            <span className="flagtag">{t("run.excludedLabel")}</span>
          ) : null}
        </div>
      ) : null}
      <div className="acts">
        {hasProfile ? (
          <Link to={cardPath} className="sm">
            {t("compare.openCard")} <span className="vh">{name}</span>
          </Link>
        ) : (
          <Link to={`/profiles/${run.id}/run`} className="sm">
            {t("compare.openProgress")} <span className="vh">{name}</span>
          </Link>
        )}
        <button type="button" className="btn-text sm" onClick={onRemove}>
          {t("compare.remove")} <span className="vh">{name}</span>
        </button>
      </div>
    </div>
  );
}

function Cell({
  item,
  field,
  sectionId,
  compact,
  headers,
  tabIndex,
  onFocus,
}: {
  item: ComparisonRun;
  field: ProfileField;
  sectionId: string;
  compact: boolean;
  headers: string;
  tabIndex: 0 | -1;
  onFocus: () => void;
}) {
  const { t, i18n } = useTranslation();
  const noteId = useId();
  const quote = useQuoteToggle();
  const cell = useRef<HTMLTableCellElement>(null);
  const { run } = item;
  const fact = item.facts.find((candidate) => candidate.field === field.id);
  const evidence = fact && fact.status !== "not_found" ? fact : null;
  const verify = field.certification
    ? (safeHttpUrl(fact?.verification_url ?? null) ?? IAF_CERTSEARCH_URL)
    : null;

  const body = () => {
    if (IN_PROGRESS.includes(run.status)) {
      return <span className="not-covered-field">{t("compare.runInProgress")}</span>;
    }
    if (run.status !== "completed" && run.status !== "partial") {
      return <span className="not-covered-field">{t("compare.noProfileCell")}</span>;
    }
    if (!fact) {
      // Not examined: never written as "No public evidence found" (a partial run, or a field the run
      // did not store).
      const partial = run.status === "partial" && run.uncovered_sections.includes(sectionId);
      return (
        <span className="not-covered-field">
          {t(partial ? "card.notCoveredField" : "compare.notExamined")}
        </span>
      );
    }
    if (!evidence) return <div className="missing">{t("card.noEvidence")}</div>;
    return (
      <>
        <div className="val">
          <Redacted text={evidence.value ?? ""} />
        </div>
        {evidence.status === "corrected" && evidence.original_value ? (
          <div className="orig">
            {t("card.originalValue")} <Redacted text={evidence.original_value} />
          </div>
        ) : null}
        <div className="cm">
          {evidence.quote ? (
            <SourceChip
              fact={evidence}
              compact
              noteId={noteId}
              open={quote.open}
              onToggle={quote.toggle}
              chipRef={quote.chip}
            />
          ) : null}
          <StatusBadge status={evidence.status as BadgeStatus} />
          <SourceTypeLabel type={evidence.source_type} />
          {evidence.quote_redacted ? <span className="ev">{t("card.redactedExtract")}</span> : null}
          {verify ? <ExternalLink href={verify}>{t("card.verifyIaf")}</ExternalLink> : null}
        </div>
        {!compact && evidence.status !== "proposed" && evidence.reviewed_at ? (
          <span className="byline">
            {t(`card.review.by.${evidence.status as "approved" | "corrected"}`, {
              who: evidence.reviewed_by_email ?? t("card.review.aMember"),
              date: formatDate(evidence.reviewed_at, i18n.language),
            })}
          </span>
        ) : null}
        {quote.open && evidence.quote ? (
          <QuoteBlock
            fact={evidence}
            fieldLabel={field.label}
            noteId={noteId}
            onClose={quote.close}
            headingRef={quote.heading}
          />
        ) : null}
      </>
    );
  };

  return (
    <td
      ref={cell}
      // biome-ignore lint/a11y/noNoninteractiveElementToInteractiveRole: grid pattern of mock-up #6
      role="gridcell"
      headers={headers}
      tabIndex={tabIndex}
      onFocus={(event) => {
        if (event.target === cell.current) onFocus();
      }}
      // A second Escape (the first one closed the quote) returns from the chip to the cell.
      onKeyDown={(event) => {
        if (event.key === "Escape" && event.target !== cell.current) {
          event.preventDefault();
          cell.current?.focus();
        }
      }}
    >
      {body()}
    </td>
  );
}

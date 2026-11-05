// The buyer context form (spec F8, Buyer input; mock-up 05-buyer-context-form): the buyer's own situation
// with this supplier. Entered by the member, stored as written, never an AI statement, so it carries no AI
// label and no provenance. Opens in the panel in place of the card body.
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../components/ui";
import {
  api,
  type BuyerContext,
  type BuyerContextUpdate,
  type FieldError,
  type StrategicIntent,
} from "../lib/api";
import { formatDateTime } from "../lib/format";

const INTENTS: StrategicIntent[] = [
  "dual_sourcing",
  "cost_reduction",
  "capacity_security",
  "risk_reduction",
];
type FieldName =
  | "current_share_pct"
  | "contract_end_date"
  | "relationship"
  | "notes"
  | "strategic_intent";
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** A number typed in the active locale ("12,5" in French) as a number, or NaN. */
export const parseShare = (text: string): number =>
  text.trim() === "" ? Number.NaN : Number(text.trim().replace(",", "."));

function validDate(text: string): boolean {
  if (!DATE.test(text)) return false;
  const parsed = new Date(`${text}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().startsWith(text);
}

type Props = {
  runId: string;
  stored: BuyerContext | null;
  /** Called with the saved context once the server has stored it. */
  onSaved: (saved: BuyerContext) => void;
  onCancel: () => void;
  /** The context stored by someone else while this form was open, to re-read the list. */
  onConflict: () => void;
};

export function BuyerContextForm({ runId, stored, onSaved, onCancel, onConflict }: Props) {
  const { t, i18n } = useTranslation();
  const base = useId();
  const [relationship, setRelationship] = useState<"incumbent" | "new">(
    stored?.relationship ?? "new",
  );
  const [share, setShare] = useState(
    stored?.current_share_pct == null ? "" : String(stored.current_share_pct),
  );
  const [end, setEnd] = useState(stored?.contract_end_date ?? "");
  const [intent, setIntent] = useState<StrategicIntent[]>(stored?.strategic_intent ?? []);
  const [notes, setNotes] = useState(stored?.notes ?? "");
  const [version, setVersion] = useState(stored?.version ?? 0);
  const [errors, setErrors] = useState<Partial<Record<FieldName, string>>>({});
  const [conflict, setConflict] = useState<BuyerContext | null | undefined>(undefined);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const summary = useRef<HTMLDivElement>(null);
  const alert = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const ids = {
    share: `${base}-share`,
    end: `${base}-end`,
    notes: `${base}-notes`,
  };

  useEffect(() => heading.current?.focus(), []);

  const labels: Record<FieldName, string> = {
    relationship: t("context.status"),
    current_share_pct: t("context.share"),
    contract_end_date: t("context.end"),
    strategic_intent: t("context.intent"),
    notes: t("context.notes"),
  };
  const targets: Record<FieldName, string> = {
    relationship: `${base}-rel-new`,
    current_share_pct: ids.share,
    contract_end_date: ids.end,
    strategic_intent: `${base}-intent-${INTENTS[0]}`,
    notes: ids.notes,
  };

  function check(): Partial<Record<FieldName, string>> {
    const found: Partial<Record<FieldName, string>> = {};
    if (share.trim() !== "") {
      const value = parseShare(share);
      if (!Number.isFinite(value) || value < 0 || value > 100) {
        found.current_share_pct = t("context.shareError");
      }
    }
    if (end.trim() !== "" && !validDate(end.trim()))
      found.contract_end_date = t("context.endError");
    return found;
  }

  function fromServer(list: FieldError[]): Partial<Record<FieldName, string>> {
    const found: Partial<Record<FieldName, string>> = {};
    for (const error of list) {
      const field = error.field as FieldName;
      if (field in labels) {
        found[field] =
          field === "current_share_pct"
            ? t("context.shareError")
            : field === "contract_end_date"
              ? t("context.endError")
              : field === "notes"
                ? t("context.notesError")
                : t("context.invalidField");
      }
    }
    return Object.keys(found).length > 0 ? found : { notes: t("context.invalidField") };
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFailed(false);
    const problems = check();
    setErrors(problems);
    if (Object.keys(problems).length > 0) {
      window.setTimeout(() => summary.current?.focus(), 0);
      return;
    }
    const body: BuyerContextUpdate = {
      relationship,
      current_share_pct: share.trim() === "" ? null : parseShare(share),
      contract_end_date: end.trim() === "" ? null : end.trim(),
      strategic_intent: intent,
      notes: notes.trim() === "" ? null : notes.trim(),
      version,
    };
    setBusy(true);
    const result = await api.putRunBuyerContext(runId, body);
    setBusy(false);
    if (result.ok) return onSaved(result.data);
    if (result.kind === "validation") {
      setErrors(fromServer(result.errors));
      window.setTimeout(() => summary.current?.focus(), 0);
    } else if (result.kind === "conflict") {
      const current = (result.current ?? null) as BuyerContext | null;
      setConflict(current);
      setVersion(current?.version ?? 0);
      onConflict();
      window.setTimeout(() => alert.current?.focus(), 0);
    } else if (result.kind !== "unauthorized") {
      setFailed(true);
      window.setTimeout(() => alert.current?.focus(), 0);
    }
  }

  const problemList = (Object.entries(errors) as [FieldName, string][]).filter(([, text]) => text);
  const intentLabel = (value: StrategicIntent) => t(`context.intents.${value}`);

  return (
    <div className="form-page">
      <h2 className="section-title" tabIndex={-1} ref={heading}>
        {t("context.title")}
        <span className="meta">{t("context.optional")}</span>
      </h2>
      <p className="section-lede">{t("context.lede")}</p>
      {stored ? (
        <p className="byline" style={{ marginTop: "var(--isc-space-2)" }}>
          {t("context.lastSaved", {
            who: stored.updated_by_email ?? t("assessment.aMember"),
            date: formatDateTime(stored.updated_at, i18n.language),
            version: stored.version,
            next: stored.version + 1,
          })}
        </p>
      ) : null}
      {conflict !== undefined ? (
        <div className="message" role="alert" tabIndex={-1} ref={alert}>
          <p>
            <strong>{t("workspace.notePrefix")}</strong>{" "}
            {conflict
              ? t("context.conflict", {
                  who: conflict.updated_by_email ?? t("assessment.aMember"),
                  date: formatDateTime(conflict.updated_at, i18n.language),
                })
              : t("context.conflictNone")}
          </p>
          {conflict ? <ContextSummary context={conflict} /> : null}
        </div>
      ) : null}
      {failed ? (
        <div className="message" role="alert" tabIndex={-1} ref={alert}>
          <p>{t("context.saveError")}</p>
        </div>
      ) : null}
      {problemList.length > 0 ? (
        <div
          className="err-summary"
          role="alert"
          tabIndex={-1}
          ref={summary}
          aria-labelledby={`${base}-es`}
        >
          <strong id={`${base}-es`}>{t("context.summary", { count: problemList.length })}</strong>
          <ul>
            {problemList.map(([field, text]) => (
              <li key={field}>
                <a
                  href={`#${targets[field]}`}
                  onClick={(event) => {
                    event.preventDefault();
                    document.getElementById(targets[field])?.focus();
                  }}
                >
                  {labels[field]}
                  {t("context.sep")} {text}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <form className="fgrid" onSubmit={submit} noValidate>
        <fieldset>
          <legend>{t("context.status")}</legend>
          <div className="help">{t("context.statusHelp")}</div>
          <label className="opt">
            <input
              type="radio"
              name={`${base}-rel`}
              checked={relationship === "incumbent"}
              onChange={() => setRelationship("incumbent")}
            />
            {t("context.incumbent")}
          </label>
          <label className="opt">
            <input
              type="radio"
              id={`${base}-rel-new`}
              name={`${base}-rel`}
              checked={relationship === "new"}
              onChange={() => setRelationship("new")}
            />
            {t("context.new")}
          </label>
        </fieldset>
        <div className={errors.current_share_pct ? "field has-error" : "field"}>
          <label htmlFor={ids.share}>{t("context.share")}</label>
          <input
            className="input input--short"
            id={ids.share}
            inputMode="decimal"
            value={share}
            onChange={(event) => setShare(event.target.value)}
            aria-invalid={errors.current_share_pct ? true : undefined}
            aria-describedby={[`${ids.share}-h`, errors.current_share_pct ? `${ids.share}-e` : null]
              .filter(Boolean)
              .join(" ")}
          />
          <span className="help" id={`${ids.share}-h`}>
            {t("context.shareHelp")}
          </span>
          {errors.current_share_pct ? (
            <span className="err" id={`${ids.share}-e`}>
              {errors.current_share_pct}
            </span>
          ) : null}
        </div>
        <div className={errors.contract_end_date ? "field has-error" : "field"}>
          <label htmlFor={ids.end}>{t("context.end")}</label>
          <input
            className="input input--short"
            id={ids.end}
            placeholder="YYYY-MM-DD"
            value={end}
            onChange={(event) => setEnd(event.target.value)}
            aria-invalid={errors.contract_end_date ? true : undefined}
            aria-describedby={[`${ids.end}-h`, errors.contract_end_date ? `${ids.end}-e` : null]
              .filter(Boolean)
              .join(" ")}
          />
          <span className="help" id={`${ids.end}-h`}>
            {t("context.endHelp")}
          </span>
          {errors.contract_end_date ? (
            <span className="err" id={`${ids.end}-e`}>
              {errors.contract_end_date}
            </span>
          ) : null}
        </div>
        <fieldset>
          <legend>{t("context.intent")}</legend>
          <div className="help">{t("context.intentHelp")}</div>
          {INTENTS.map((value) => (
            <label className="opt" key={value}>
              <input
                type="checkbox"
                id={`${base}-intent-${value}`}
                checked={intent.includes(value)}
                onChange={(event) =>
                  setIntent((was) =>
                    event.target.checked ? [...was, value] : was.filter((item) => item !== value),
                  )
                }
              />
              {intentLabel(value)}
            </label>
          ))}
        </fieldset>
        <div className={errors.notes ? "field has-error" : "field"}>
          <label htmlFor={ids.notes}>{t("context.notes")}</label>
          <textarea
            className="textarea"
            id={ids.notes}
            rows={4}
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            aria-invalid={errors.notes ? true : undefined}
            aria-describedby={[`${ids.notes}-h`, errors.notes ? `${ids.notes}-e` : null]
              .filter(Boolean)
              .join(" ")}
            dir="auto"
          />
          <span className="help" id={`${ids.notes}-h`}>
            {t("context.notesHelp")}
          </span>
          {errors.notes ? (
            <span className="err" id={`${ids.notes}-e`}>
              {errors.notes}
            </span>
          ) : null}
        </div>
        <div className="form-row">
          <Button type="submit" variant="primary" loading={busy} loadingLabel={t("context.saving")}>
            {conflict !== undefined ? t("context.apply") : t("context.save")}
          </Button>
          <Button variant="secondary" onClick={onCancel}>
            {t("context.cancel")}
          </Button>
        </div>
        <p className="help">{t("context.afterSave")}</p>
      </form>
    </div>
  );
}

/** The stored buyer context as a list of its values. */
export function ContextSummary({ context }: { context: BuyerContext }) {
  const { t, i18n } = useTranslation();
  return (
    <dl className="kv">
      <dt>{t("context.supplier")}</dt>
      <dd>{t(context.relationship === "incumbent" ? "context.incumbent" : "context.new")}</dd>
      {context.current_share_pct == null ? null : (
        <>
          <dt>{t("context.shareShort")}</dt>
          <dd>
            {new Intl.NumberFormat(i18n.language === "fr" ? "fr-FR" : "en-US", {
              style: "percent",
              maximumFractionDigits: 2,
            }).format(context.current_share_pct / 100)}
          </dd>
        </>
      )}
      {context.contract_end_date ? (
        <>
          <dt>{t("context.endShort")}</dt>
          <dd>
            {new Intl.DateTimeFormat(i18n.language === "fr" ? "fr-FR" : "en-US", {
              dateStyle: "medium",
              timeZone: "UTC",
            }).format(new Date(`${context.contract_end_date}T00:00:00Z`))}
          </dd>
        </>
      ) : null}
      {context.strategic_intent.length > 0 ? (
        <>
          <dt>{t("context.intent")}</dt>
          <dd>
            {context.strategic_intent.map((value) => t(`context.intents.${value}`)).join(", ")}
          </dd>
        </>
      ) : null}
      {context.notes ? (
        <>
          <dt>{t("context.notes")}</dt>
          <dd>{context.notes}</dd>
        </>
      ) : null}
    </dl>
  );
}

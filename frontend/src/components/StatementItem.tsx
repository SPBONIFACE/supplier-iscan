// One assessment statement (spec F8; mock-ups 05-assessment-review, 05-recommendations-*): its text, level or
// label, cited facts, the AI-draft label until a member decides, Approve, Correct and Delete (with a
// confirmation), and provenance on demand. Everything from the API is rendered as text.
import {
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import type { AssessmentStatement } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { AiDraftLabel } from "./AiDraftLabel";
import { Button } from "./ui";

export type StatementBody =
  | { status: "approved" }
  | { status: "corrected"; text: string }
  | { status: "deleted" };

export type StatementOutcome =
  | { kind: "saved"; statement: AssessmentStatement }
  /** Someone reviewed the statement since the member read it; `current` is its state now. */
  | { kind: "conflict"; current: AssessmentStatement | null }
  | { kind: "in_progress" }
  | { kind: "signed_out" }
  | { kind: "rejected" }
  | { kind: "gone" }
  | { kind: "invalid" }
  | { kind: "error" };

export type StatementControls = {
  /** The reason the actions are off (the run is still in progress), else null. */
  lockedReason: string | null;
  lockedId: string;
  submit: (item: AssessmentStatement, body: StatementBody) => Promise<StatementOutcome>;
  reload: () => void;
};

/** A cited fact, as the statement shows it. */
export type CitedFact = {
  id: string;
  label: string;
  correctedAfterDraft: boolean;
  /** The note number of the fact's source on the card page; it links to the entry in Sources. */
  note?: number | null;
};

export type StatementProps = {
  item: AssessmentStatement;
  /** Names the kind of a recommendation ("Contract approach"). */
  kindLabel?: string;
  cited: CitedFact[];
  controls: StatementControls;
  /** The statement is written by rules in code (the financial guidance), not by a model. */
  byRules?: boolean;
  /** Recommendations: whether a redraft would replace this statement. */
  redraftNote?: "replaces" | "keeps" | null;
  /** Offers to redraft when a cited fact was corrected after the draft; null when no redraft exists. */
  onRedraft?: (() => void) | null;
  redraftDisabled?: boolean;
  /** Where the buyer-context citation points. */
  contextHref?: string;
  /** Extra content between the text and the meta line (the financial tables). */
  children?: ReactNode;
};

const ASSUMPTIONS = [
  "Assuming a first evaluation of this supplier:",
  "En supposant une première évaluation de ce fournisseur :",
  "En supposant une première évaluation de ce fournisseur :",
];

/** The text of a statement; the first-evaluation assumption is set apart so it reads as drafted. */
function StatementText({ text }: { text: string }) {
  const prefix = ASSUMPTIONS.find((candidate) => text.startsWith(candidate));
  if (!prefix) return <>{text}</>;
  return (
    <>
      <span className="assume">{prefix}</span>
      {text.slice(prefix.length)}
    </>
  );
}

export function StatementItem({
  item,
  kindLabel,
  cited,
  controls,
  byRules = false,
  redraftNote = null,
  onRedraft = null,
  redraftDisabled = false,
  contextHref = "#ctx",
  children,
}: StatementProps) {
  const { t, i18n } = useTranslation();
  const base = useId();
  const row = useRef<HTMLLIElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const noticeBox = useRef<HTMLDivElement>(null);
  const confirmButton = useRef<HTMLButtonElement>(null);
  const [mode, setMode] = useState<"idle" | "editing" | "deleting">("idle");
  const [draft, setDraft] = useState("");
  const [fieldError, setFieldError] = useState<"empty" | "invalid" | null>(null);
  const [notice, setNotice] = useState<
    | { kind: "conflict"; who: string; when: string | null; typed: boolean }
    | { kind: "gone" }
    | { kind: "error" }
    | { kind: "rejected" }
    | null
  >(null);
  const [showProv, setShowProv] = useState(false);
  const [busy, setBusy] = useState(false);
  const status = item.provenance.status;
  const locked = controls.lockedReason !== null;
  const provId = `${base}-prov`;
  const who = (email: string | null | undefined) => email ?? t("assessment.aMember");

  useEffect(() => {
    if (mode === "editing") field.current?.focus();
    if (mode === "deleting") confirmButton.current?.focus();
  }, [mode]);
  useEffect(() => {
    if (notice) noticeBox.current?.focus();
  }, [notice]);

  const reviewedBy =
    status !== "ai_draft" && item.provenance.reviewed_at
      ? t("assessment.reviewedBy", {
          who: who(item.provenance.reviewed_by_email),
          date: formatDateTime(item.provenance.reviewed_at, i18n.language),
        })
      : null;

  const focusRow = () => row.current?.focus();

  function handle(outcome: StatementOutcome, deleting: boolean) {
    switch (outcome.kind) {
      case "saved": {
        setNotice(null);
        setFieldError(null);
        setMode("idle");
        if (deleting) {
          // The statement leaves the section: focus goes to the next one, else to the one before,
          // else to the heading of the section (the group heading goes with its last statement).
          const li = row.current;
          const target =
            li?.nextElementSibling ??
            li?.previousElementSibling ??
            li?.closest("section")?.querySelector("h2") ??
            null;
          window.setTimeout(() => (target as HTMLElement | null)?.focus(), 0);
        } else {
          focusRow();
        }
        break;
      }
      case "conflict":
        setNotice({
          kind: "conflict",
          who: outcome.current ? who(outcome.current.provenance.reviewed_by_email) : who(null),
          when: outcome.current?.provenance.reviewed_at
            ? formatDateTime(outcome.current.provenance.reviewed_at, i18n.language)
            : null,
          typed: mode === "editing",
        });
        if (mode === "deleting") setMode("idle");
        break;
      case "in_progress":
      case "signed_out":
        setNotice(null);
        setMode("idle");
        focusRow();
        break;
      case "invalid":
        setFieldError("invalid");
        field.current?.focus();
        break;
      case "gone":
        setNotice({ kind: "gone" });
        setMode("idle");
        break;
      case "rejected":
        setNotice({ kind: "rejected" });
        setMode("idle");
        break;
      default:
        setNotice({ kind: "error" });
        setMode("idle");
    }
  }

  async function send(body: StatementBody) {
    setNotice(null);
    setBusy(true);
    const outcome = await controls.submit(item, body);
    setBusy(false);
    handle(outcome, body.status === "deleted");
  }

  function openForm() {
    setNotice(null);
    setFieldError(null);
    setDraft(item.text);
    setMode("editing");
  }

  async function save(event?: FormEvent) {
    event?.preventDefault();
    const text = draft.trim();
    if (!text) {
      setFieldError("empty"); // nothing is sent
      field.current?.focus();
      return;
    }
    setFieldError(null);
    await send({ status: "corrected", text });
  }

  function cancel() {
    setMode("idle");
    setFieldError(null);
    setNotice(null);
    focusRow();
  }

  const onFormKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation(); // cancels the form, not the panel
      cancel();
    } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      void save();
    }
  };
  const onConfirmKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation(); // keeps the statement, not closes the panel
      cancel();
    }
  };

  const actionProps = locked
    ? { disabled: true, "aria-describedby": controls.lockedId }
    : { disabled: busy };
  const name = kindLabel ?? t(`assessment.kinds.${item.kind}`);
  const fieldId = `${base}-text`;
  const errorId = `${base}-error`;
  const changed = cited.filter((fact) => fact.correctedAfterDraft);
  const provTime = formatDateTime(item.provenance.generated_at, i18n.language);

  return (
    <li className="stmt" id={`stmt-${item.id}`} ref={row} tabIndex={-1}>
      {mode === "editing" ? (
        <form
          aria-label={t("assessment.formLabel", { kind: name })}
          onSubmit={save}
          onKeyDown={onFormKey}
          noValidate
        >
          <div className={fieldError ? "field has-error" : "field"}>
            <label htmlFor={fieldId}>
              {notice?.kind === "conflict"
                ? t("assessment.yourText")
                : t("assessment.correctedText")}
            </label>
            <textarea
              className="textarea"
              id={fieldId}
              ref={field}
              rows={3}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              aria-invalid={fieldError ? true : undefined}
              aria-describedby={[fieldError ? errorId : null, `${fieldId}-help`]
                .filter(Boolean)
                .join(" ")}
              dir="auto"
            />
            {fieldError ? (
              <span className="err" id={errorId}>
                {t(fieldError === "empty" ? "assessment.emptyText" : "assessment.invalidText")}
              </span>
            ) : null}
            <p className="help" id={`${fieldId}-help`}>
              {t("assessment.correctHelp")}
            </p>
          </div>
          <div className="stmt-meta">
            <CitesLine cited={cited} item={item} contextHref={contextHref} />
          </div>
          <div className="form-row">
            <Button
              type="submit"
              variant="primary"
              loading={busy}
              loadingLabel={t("assessment.saving")}
              disabled={locked}
              aria-describedby={locked ? controls.lockedId : undefined}
            >
              {notice?.kind === "conflict" ? t("assessment.apply") : t("assessment.save")}
            </Button>
            <Button variant="secondary" onClick={cancel}>
              {notice?.kind === "conflict" ? t("assessment.discard") : t("assessment.cancel")}
            </Button>
            <span className="kbd-hint">{t("assessment.keys")}</span>
          </div>
        </form>
      ) : (
        <>
          {byRules || item.kind === "evidence_gap" ? (
            <div className="gap">
              <span className="gap-label">{t("assessment.kinds.evidence_gap")}</span>
              <p className="stmt-text">{item.text}</p>
            </div>
          ) : (
            <>
              {kindLabel ? <span className="reco-kind">{kindLabel}</span> : null}
              <p className="stmt-text">
                <StatementText text={item.text} />
              </p>
            </>
          )}
          {item.kind === "evidence_gap" && item.gap_evidence ? (
            <p className="stmt-text">
              <strong>{t("assessment.wouldClose")}</strong> {item.gap_evidence}
            </p>
          ) : null}
          {children}
          <div className="stmt-meta">
            {item.level ? (
              <span className="level">
                {t("assessment.level")} <strong>{t(`assessment.levels.${item.level}`)}</strong>
              </span>
            ) : null}
            {item.label ? (
              <span className="level">
                {t("assessment.relationship")}{" "}
                <strong>{t(`assessment.relationships.${item.label}`)}</strong>
              </span>
            ) : null}
            {item.timing ? (
              <span className="level">
                {t("assessment.timing")} <strong>{item.timing}</strong>
              </span>
            ) : null}
            <CitesLine cited={cited} item={item} contextHref={contextHref} />
          </div>
          {changed.length > 0 && status !== "deleted" ? (
            <div className="cited-changed">
              <p>
                {t("assessment.citedCorrected", {
                  facts: changed.map((fact) => fact.label).join(", "),
                })}
              </p>
              {onRedraft ? (
                <Button variant="secondary" onClick={onRedraft} disabled={redraftDisabled}>
                  {item.kind === "fit"
                    ? t("assessment.redraftFit")
                    : t("assessment.redraftRecommendations")}
                </Button>
              ) : null}
            </div>
          ) : null}
          {redraftNote ? (
            <p className="will-replace">
              {t(redraftNote === "replaces" ? "assessment.willReplace" : "assessment.willKeep")}
            </p>
          ) : null}
          <div className="stmt-foot">
            <AiDraftLabel status={status} byRules={byRules} />
            {reviewedBy ? <span className="byline">{reviewedBy}</span> : null}
            <button
              type="button"
              className="disclosure"
              aria-expanded={showProv}
              aria-controls={provId}
              onClick={() => setShowProv((open) => !open)}
            >
              {t("assessment.provenance")} <span className="vh">{name}</span>
            </button>
            {mode === "idle" ? (
              <div className="stmt-actions">
                {status === "ai_draft" ? (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => void send({ status: "approved" })}
                    {...actionProps}
                  >
                    {t("assessment.approve")} <span className="vh">{name}</span>
                  </button>
                ) : null}
                <button type="button" className="btn btn-text" onClick={openForm} {...actionProps}>
                  {t("assessment.correct")} <span className="vh">{name}</span>
                </button>
                <button
                  type="button"
                  className="btn btn-text"
                  onClick={() => {
                    setNotice(null);
                    setMode("deleting");
                  }}
                  {...actionProps}
                >
                  {t("assessment.delete")} <span className="vh">{name}</span>
                </button>
              </div>
            ) : null}
          </div>
          {showProv ? (
            <div className="prov" id={provId}>
              <dl>
                <dt>{t("assessment.provider")}</dt>
                <dd>
                  {item.provenance.provider === "rules"
                    ? t("assessment.rules")
                    : item.provenance.provider}
                </dd>
                {item.provenance.provider === "rules" ? null : (
                  <>
                    <dt>{t("assessment.model")}</dt>
                    <dd className="mono">
                      {item.provenance.model_id} · {item.provenance.model_version}
                    </dd>
                  </>
                )}
                <dt>{t("assessment.generated")}</dt>
                <dd>{provTime}</dd>
                <dt>{t("assessment.reviewStatus")}</dt>
                <dd>
                  {status === "ai_draft"
                    ? t("assessment.notReviewedYet")
                    : `${t(`assessment.status.${status}`)}${reviewedBy ? `, ${reviewedBy.charAt(0).toLowerCase()}${reviewedBy.slice(1)}` : ""}`}
                </dd>
              </dl>
              {item.original_text ? (
                <div className="hist">
                  <dl>
                    <dt>{t("assessment.aiText")}</dt>
                    <dd>{item.original_text}</dd>
                  </dl>
                </div>
              ) : null}
            </div>
          ) : null}
        </>
      )}
      {mode === "deleting" ? (
        <div
          className="message"
          role="alertdialog"
          aria-labelledby={`${base}-del`}
          onKeyDown={onConfirmKey}
        >
          <p id={`${base}-del`}>
            <strong>{t("assessment.deleteTitle")}</strong> {t("assessment.deleteBody")}
          </p>
          <div className="form-row">
            <button
              type="button"
              className="btn btn-primary"
              ref={confirmButton}
              onClick={() => void send({ status: "deleted" })}
              disabled={busy}
            >
              {t("assessment.deleteConfirm")}
            </button>
            <Button variant="secondary" onClick={cancel}>
              {t("assessment.keep")}
            </Button>
          </div>
        </div>
      ) : null}
      {notice ? (
        <div className="message" role="alert" tabIndex={-1} ref={noticeBox}>
          {notice.kind === "conflict" ? (
            <p>
              <strong>{t("workspace.notePrefix")}</strong>{" "}
              {t(notice.typed ? "assessment.conflictTyped" : "assessment.conflict", {
                who: notice.who,
                date: notice.when ?? "",
              })}
            </p>
          ) : notice.kind === "error" ? (
            <p>{t("assessment.error")}</p>
          ) : (
            <>
              <p>{t(notice.kind === "gone" ? "assessment.gone" : "assessment.rejected")}</p>
              <p>
                <button type="button" className="btn btn-secondary" onClick={controls.reload}>
                  {t("assessment.reload")}
                </button>
              </p>
            </>
          )}
        </div>
      ) : null}
    </li>
  );
}

/** "Cites: Production sites · Buyer context, version 2": each fact links to its row on the card. */
function CitesLine({
  cited,
  item,
  contextHref,
}: {
  cited: CitedFact[];
  item: AssessmentStatement;
  contextHref: string;
}) {
  const { t } = useTranslation();
  const context = item.cites_buyer_context;
  if (cited.length === 0 && !context) return null;
  return (
    <span>
      {t("assessment.cites")}{" "}
      <ul className="cites">
        {cited.map((fact) => (
          <li key={fact.id}>
            <a
              href={`#fact-${fact.id}`}
              onClick={(event) => {
                event.preventDefault();
                document.getElementById(`fact-${fact.id}`)?.focus();
              }}
            >
              {fact.label}
            </a>
            {fact.note ? (
              <sup className="note-ref">
                <a href={`#n${fact.note}`} aria-label={t("card.noteLink", { number: fact.note })}>
                  {fact.note}
                </a>
              </sup>
            ) : null}
          </li>
        ))}
        {context ? (
          <li>
            <a
              className="ctx-cite"
              href={contextHref}
              onClick={(event) => {
                event.preventDefault();
                document.getElementById("ctx")?.focus();
              }}
            >
              {item.buyer_context_version
                ? t("assessment.contextVersion", { version: item.buyer_context_version })
                : t("assessment.context")}
            </a>
          </li>
        ) : null}
      </ul>
    </span>
  );
}

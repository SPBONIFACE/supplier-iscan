// Review of one fact on the supplier card (#36, spec F4; mock-ups 05-review-default, -correction,
// -conflict): Approve, Correct (an inline form), who reviewed and when, and the plain messages for a
// concurrent edit, a run still in progress, a fact that is gone and a failed save. The AI proposes, the
// member decides: nothing here changes a fact without the member pressing a button.
import { type FormEvent, type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Fact } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { Button } from "./ui";

export type ReviewBody = { status: "approved" } | { status: "corrected"; value: string };

/** What came back from a review, in the terms the row acts on. */
export type ReviewOutcome =
  | { kind: "saved"; fact: Fact }
  /** Someone reviewed the fact since the member read it; `current` is its state now. */
  | { kind: "conflict"; current: Fact | null }
  | { kind: "in_progress" }
  /** 401: the app is sending the member to sign in; nothing to show on the row. */
  | { kind: "signed_out" }
  /** 409 for another reason (nothing to review, a corrected fact to approve). */
  | { kind: "rejected" }
  | { kind: "gone" }
  | { kind: "invalid" }
  | { kind: "error" };

export type ReviewControls = {
  /** The reason the actions are off (the run is still in progress), else null. */
  lockedReason: string | null;
  /** Id of the element that shows that reason. */
  lockedId: string;
  submit: (fact: Fact, label: string, body: ReviewBody) => Promise<ReviewOutcome>;
  /** Reads the card again (after a fact that is gone). */
  reload: () => void;
};

type Notice =
  | { kind: "conflict"; who: string | null; when: string | null; typed: boolean }
  | { kind: "gone" }
  | { kind: "error" }
  | { kind: "rejected" };

type Props = {
  fact: Fact;
  label: string;
  review: ReviewControls;
  /** Gives the focus back to the row after an action. */
  focusRow: () => void;
};

export function FactReviewBar({ fact, label, review, focusRow }: Props) {
  const { t, i18n } = useTranslation();
  const base = useId();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [fieldError, setFieldError] = useState<"empty" | "invalid" | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const noticeBox = useRef<HTMLDivElement>(null);
  const locked = review.lockedReason !== null;

  // Focus goes into the field when it opens, and to the message when one appears.
  useEffect(() => {
    if (editing) input.current?.focus();
  }, [editing]);
  useEffect(() => {
    if (notice) noticeBox.current?.focus();
  }, [notice]);

  const who = (email: string | null | undefined) => email ?? t("card.review.aMember");
  const byline =
    (fact.status === "approved" || fact.status === "corrected") && fact.reviewed_at
      ? t(`card.review.by.${fact.status}`, {
          who: who(fact.reviewed_by_email),
          date: formatDateTime(fact.reviewed_at, i18n.language),
        })
      : null;

  function finish(outcome: ReviewOutcome, fromForm: boolean) {
    switch (outcome.kind) {
      case "saved":
        setNotice(null);
        setEditing(false);
        setFieldError(null);
        focusRow();
        break;
      case "conflict":
        // The row now shows the current state; the member's text stays in the form.
        setNotice({
          kind: "conflict",
          who: outcome.current ? who(outcome.current.reviewed_by_email) : t("card.review.aMember"),
          when: outcome.current?.reviewed_at
            ? formatDateTime(outcome.current.reviewed_at, i18n.language)
            : null,
          typed: fromForm,
        });
        break;
      case "in_progress":
      case "signed_out":
        setNotice(null);
        focusRow();
        break;
      case "invalid":
        setFieldError("invalid");
        input.current?.focus();
        break;
      case "gone":
        setNotice({ kind: "gone" });
        break;
      case "rejected":
        setNotice({ kind: "rejected" });
        break;
      default:
        setNotice({ kind: "error" });
    }
  }

  async function approve() {
    setNotice(null);
    setBusy(true);
    const outcome = await review.submit(fact, label, { status: "approved" });
    setBusy(false);
    finish(outcome, false);
  }

  function openForm() {
    setNotice(null);
    setFieldError(null);
    setDraft(fact.value ?? "");
    setEditing(true);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    const value = draft.trim();
    if (!value) {
      setFieldError("empty"); // nothing is sent
      input.current?.focus();
      return;
    }
    setFieldError(null);
    setBusy(true);
    const outcome = await review.submit(fact, label, { status: "corrected", value });
    setBusy(false);
    finish(outcome, true);
  }

  function cancel() {
    setEditing(false);
    setFieldError(null);
    setNotice(null);
    focusRow();
  }

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation(); // cancels the form, not the panel
      cancel();
    }
  };

  const conflictInForm = editing && notice?.kind === "conflict";
  const fieldId = `${base}-value`;
  const helpId = `${base}-help`;
  const errorId = `${base}-error`;
  const describedBy = [fieldError ? errorId : null, helpId].filter(Boolean).join(" ");
  const actionProps = locked
    ? { disabled: true, "aria-describedby": review.lockedId }
    : { disabled: busy };

  return (
    <>
      <div className="f-review">
        {byline ? <span className="byline">{byline}</span> : <span />}
        {editing ? null : (
          <div className="f-actions">
            {fact.status === "proposed" ? (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={approve}
                {...actionProps}
              >
                {t("card.review.approve")} <span className="vh">{label}</span>
              </button>
            ) : null}
            <button type="button" className="btn btn-text" onClick={openForm} {...actionProps}>
              {t("card.review.correct")} <span className="vh">{label}</span>
            </button>
          </div>
        )}
      </div>
      {notice ? (
        <div className="message" role="alert" tabIndex={-1} ref={noticeBox}>
          {notice.kind === "conflict" ? (
            <p>
              <strong>{t("workspace.notePrefix")}</strong>{" "}
              {t(notice.typed ? "card.review.conflictTyped" : "card.review.conflict", {
                who: notice.who,
                date: notice.when ?? "",
              })}
            </p>
          ) : notice.kind === "gone" ? (
            <>
              <p>{t("card.review.gone")}</p>
              <p>
                <button type="button" className="btn btn-secondary" onClick={review.reload}>
                  {t("card.review.reload")}
                </button>
              </p>
            </>
          ) : notice.kind === "rejected" ? (
            <>
              <p>{t("card.review.rejected")}</p>
              <p>
                <button type="button" className="btn btn-secondary" onClick={review.reload}>
                  {t("card.review.reload")}
                </button>
              </p>
            </>
          ) : (
            <p>{t("card.review.error")}</p>
          )}
        </div>
      ) : null}
      {editing ? (
        <form
          className="f-form"
          aria-label={t("card.review.formLabel", { field: label })}
          onSubmit={save}
          onKeyDown={onKeyDown}
          noValidate
        >
          <div className={fieldError ? "field has-error" : "field"}>
            <label htmlFor={fieldId}>
              {conflictInForm ? t("card.review.yourValue") : t("card.review.correctedValue")}
            </label>
            <input
              className="input"
              id={fieldId}
              ref={input}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              aria-invalid={fieldError ? true : undefined}
              aria-describedby={describedBy}
              dir="auto"
            />
            {fieldError ? (
              <span className="err" id={errorId}>
                {t(fieldError === "empty" ? "card.review.emptyValue" : "card.review.invalid")}
              </span>
            ) : null}
            <p className="help" id={helpId}>
              {t("card.review.help")}
            </p>
          </div>
          <div className="form-row">
            <Button
              type="submit"
              variant="primary"
              loading={busy}
              loadingLabel={t("card.review.saving")}
              disabled={locked}
              aria-describedby={locked ? review.lockedId : undefined}
            >
              {conflictInForm ? t("card.review.apply") : t("card.review.save")}
            </Button>
            <Button variant="secondary" onClick={cancel}>
              {conflictInForm ? t("card.review.discard") : t("card.review.cancel")}
            </Button>
            <span className="kbd-hint">{t("card.review.keys")}</span>
          </div>
        </form>
      ) : null}
    </>
  );
}

// The member's own text on the supplier card (spec F8): the fit criteria and the free-text fields of kind
// `buyer`. Both are entered by members, stored as written, never drafted by the AI and never labelled as AI
// content; each shows who last saved it and when. A concurrent save (409) shows the value stored now and
// keeps the member's text, so no edit is silently lost.
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../components/ui";
import { api, type BuyerInput, type Criteria } from "../lib/api";
import { formatDateTime } from "../lib/format";

const lines = (text: string): string[] =>
  text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");

type CriteriaProps = {
  runId: string;
  stored: Criteria | null;
  onSaved: () => Promise<void>;
  announce: (message: string) => void;
  /** Lets the "Go to the criteria field" link reach the field. */
  fieldRef: React.RefObject<HTMLTextAreaElement | null>;
};

/** The fit criteria: a saved list with "Edit criteria", or the field to enter them. */
export function CriteriaBox({ runId, stored, onSaved, announce, fieldRef }: CriteriaProps) {
  const { t, i18n } = useTranslation();
  const id = useId();
  const has = (stored?.criteria.length ?? 0) > 0;
  const [editing, setEditing] = useState(!has);
  const [draft, setDraft] = useState((stored?.criteria ?? []).join("\n"));
  const [version, setVersion] = useState(stored?.version ?? 0);
  const [error, setError] = useState<"invalid" | "failed" | null>(null);
  const [conflict, setConflict] = useState<Criteria | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const editButton = useRef<HTMLButtonElement>(null);
  const alert = useRef<HTMLDivElement>(null);
  const wasEditing = useRef(false);

  // What is stored changed under us (after a save, a reload): follow it unless the member is typing.
  useEffect(() => {
    if (!editing) {
      setDraft((stored?.criteria ?? []).join("\n"));
      setVersion(stored?.version ?? 0);
    }
  }, [stored, editing]);
  useEffect(() => {
    if (!editing && wasEditing.current) editButton.current?.focus();
    wasEditing.current = editing;
  }, [editing]);

  async function save(event: FormEvent) {
    event.preventDefault();
    const list = lines(draft);
    if (list.length === 0 && draft.trim() !== "") return;
    setBusy(true);
    setError(null);
    const result = await api.putRunCriteria(runId, { criteria: list, version });
    setBusy(false);
    if (result.ok) {
      setConflict(undefined);
      await onSaved();
      setVersion(result.data.version);
      setEditing(result.data.criteria.length === 0);
      announce(t("assessment.criteriaSaved"));
    } else if (result.kind === "conflict") {
      const current = (result.current ?? null) as Criteria | null;
      setConflict(current);
      setVersion(current?.version ?? 0);
      await onSaved();
      window.setTimeout(() => alert.current?.focus(), 0);
    } else if (result.kind === "validation") {
      setError("invalid");
      fieldRef.current?.focus();
    } else if (result.kind !== "unauthorized") {
      setError("failed");
      window.setTimeout(() => alert.current?.focus(), 0);
    }
  }

  return (
    <div id={`${id}-box`}>
      {has && !editing ? (
        <div className="criteria-saved" id="criteria">
          <p
            className="label"
            style={{
              fontSize: "var(--isc-font-size-sm)",
              fontWeight: "var(--isc-font-weight-semibold)",
            }}
          >
            {t("assessment.criteriaTitle")}
          </p>
          <ul>
            {stored?.criteria.map((criterion, index) => (
              <li key={`${index}-${criterion}`}>{criterion}</li>
            ))}
          </ul>
          {stored ? (
            <p className="byline" style={{ marginTop: "var(--isc-space-2)" }}>
              {t("assessment.savedBy", {
                who: stored.updated_by_email ?? t("assessment.aMember"),
                date: formatDateTime(stored.updated_at, i18n.language),
              })}{" "}
              ·{" "}
              <button
                type="button"
                className="btn btn-text"
                ref={editButton}
                onClick={() => {
                  setDraft(stored.criteria.join("\n"));
                  setVersion(stored.version);
                  setEditing(true);
                }}
              >
                {t("assessment.criteriaEdit")}
              </button>
            </p>
          ) : null}
        </div>
      ) : (
        <form onSubmit={save} noValidate style={{ marginTop: "var(--isc-space-4)" }}>
          {conflict !== undefined ? (
            <div className="message" role="alert" tabIndex={-1} ref={alert}>
              <p>
                <strong>{t("workspace.notePrefix")}</strong>{" "}
                {conflict
                  ? t("assessment.criteriaConflict", {
                      who: conflict.updated_by_email ?? t("assessment.aMember"),
                      date: formatDateTime(conflict.updated_at, i18n.language),
                    })
                  : t("assessment.criteriaConflictNone")}
              </p>
              {conflict && conflict.criteria.length > 0 ? (
                <ul>
                  {conflict.criteria.map((criterion, index) => (
                    <li key={`${index}-${criterion}`}>{criterion}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          {error === "failed" ? (
            <div className="message" role="alert" tabIndex={-1} ref={alert}>
              <p>{t("assessment.saveError")}</p>
            </div>
          ) : null}
          <div className={error === "invalid" ? "field has-error" : "field"}>
            <label htmlFor={`${id}-field`}>{t("assessment.criteriaLabel")}</label>
            <textarea
              className="textarea"
              id={`${id}-field`}
              ref={fieldRef}
              rows={4}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={t("assessment.criteriaPlaceholder")}
              aria-invalid={error === "invalid" ? true : undefined}
              aria-describedby={[`${id}-help`, error === "invalid" ? `${id}-err` : null]
                .filter(Boolean)
                .join(" ")}
              dir="auto"
            />
            <p className="help" id={`${id}-help`}>
              {t("assessment.criteriaHelp")}
            </p>
            {error === "invalid" ? (
              <span className="err" id={`${id}-err`}>
                {t("assessment.criteriaInvalid")}
              </span>
            ) : null}
          </div>
          <div className="form-row">
            <Button
              type="submit"
              variant="secondary"
              loading={busy}
              loadingLabel={t("assessment.saving")}
            >
              {conflict !== undefined ? t("assessment.apply") : t("assessment.criteriaSave")}
            </Button>
            {has ? (
              <Button
                variant="text"
                onClick={() => {
                  setConflict(undefined);
                  setError(null);
                  setEditing(false);
                }}
              >
                {t("assessment.cancel")}
              </Button>
            ) : null}
          </div>
        </form>
      )}
    </div>
  );
}

type Field = { id: string; label: string };

type InputsProps = {
  runId: string;
  fields: Field[];
  stored: BuyerInput[];
  onSaved: () => Promise<void>;
  announce: (message: string) => void;
};

/** One free-text field per field of kind `buyer`, and one button that saves what changed. */
export function BuyerInputFields({ runId, fields, stored, onSaved, announce }: InputsProps) {
  const { t, i18n } = useTranslation();
  const base = useId();
  const byField = new Map(stored.map((item) => [item.field, item]));
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [versions, setVersions] = useState<Record<string, number>>({});
  const [errors, setErrors] = useState<Record<string, "invalid" | "failed">>({});
  const [conflicts, setConflicts] = useState<Record<string, BuyerInput | null>>({});
  const [busy, setBusy] = useState(false);
  const alert = useRef<HTMLDivElement>(null);
  const [problem, setProblem] = useState(false);

  const textOf = (field: string) => texts[field] ?? byField.get(field)?.text ?? "";
  const versionOf = (field: string) => versions[field] ?? byField.get(field)?.version ?? 0;
  const dirty = fields.filter((field) => textOf(field.id) !== (byField.get(field.id)?.text ?? ""));

  async function save(event: FormEvent) {
    event.preventDefault();
    if (dirty.length === 0) return;
    setBusy(true);
    setProblem(false);
    const nextErrors: Record<string, "invalid" | "failed"> = {};
    const nextConflicts: Record<string, BuyerInput | null> = {};
    const nextTexts = { ...texts };
    const nextVersions = { ...versions };
    let saved = 0;
    for (const field of dirty) {
      const result = await api.putRunBuyerInput(runId, field.id, {
        text: textOf(field.id),
        version: versionOf(field.id),
      });
      if (result.ok) {
        saved += 1;
        delete nextTexts[field.id];
        nextVersions[field.id] = result.data.version;
      } else if (result.kind === "conflict") {
        const current = (result.current ?? null) as BuyerInput | null;
        nextConflicts[field.id] = current;
        nextVersions[field.id] = current?.version ?? 0;
      } else if (result.kind === "validation") {
        nextErrors[field.id] = "invalid";
      } else if (result.kind !== "unauthorized") {
        nextErrors[field.id] = "failed";
      }
    }
    setErrors(nextErrors);
    setConflicts(nextConflicts);
    setTexts(nextTexts);
    setVersions(nextVersions);
    if (saved > 0 || Object.keys(nextConflicts).length > 0) await onSaved();
    setBusy(false);
    if (Object.keys(nextErrors).length + Object.keys(nextConflicts).length > 0) {
      setProblem(true);
      window.setTimeout(() => alert.current?.focus(), 0);
    } else if (saved > 0) {
      announce(t("assessment.inputSaved"));
    }
  }

  if (fields.length === 0) return null;
  return (
    <form className="buyer" onSubmit={save} noValidate>
      {problem ? (
        <div className="message" role="alert" tabIndex={-1} ref={alert}>
          <p>{t("assessment.inputProblem")}</p>
        </div>
      ) : null}
      {fields.map((field) => {
        const item = byField.get(field.id);
        const conflict = conflicts[field.id];
        const error = errors[field.id];
        const id = `${base}-${field.id}`;
        return (
          <div
            className={error === "invalid" ? "field buyer-field has-error" : "field buyer-field"}
            key={field.id}
          >
            <label htmlFor={id}>{field.label}</label>
            <textarea
              className="textarea"
              id={id}
              rows={3}
              value={textOf(field.id)}
              onChange={(event) => setTexts((was) => ({ ...was, [field.id]: event.target.value }))}
              aria-invalid={error === "invalid" ? true : undefined}
              aria-describedby={error || conflict !== undefined ? `${id}-note` : undefined}
              dir="auto"
            />
            {error || conflict !== undefined ? (
              <div className="message" id={`${id}-note`}>
                {error === "invalid" ? <p className="err">{t("assessment.inputInvalid")}</p> : null}
                {error === "failed" ? <p>{t("assessment.saveError")}</p> : null}
                {conflict !== undefined ? (
                  <>
                    <p>
                      <strong>{t("workspace.notePrefix")}</strong>{" "}
                      {conflict
                        ? t("assessment.inputConflict", {
                            who: conflict.updated_by_email ?? t("assessment.aMember"),
                            date: formatDateTime(conflict.updated_at, i18n.language),
                          })
                        : t("assessment.inputConflictNone")}
                    </p>
                    {conflict ? <p className="stmt-text">{conflict.text}</p> : null}
                  </>
                ) : null}
              </div>
            ) : null}
            <p className="byline">
              {item
                ? t("assessment.lastSaved", {
                    who: item.updated_by_email ?? t("assessment.aMember"),
                    date: formatDateTime(item.updated_at, i18n.language),
                  })
                : t("assessment.notSavedYet")}
            </p>
          </div>
        );
      })}
      <div className="form-row">
        <Button
          type="submit"
          variant="secondary"
          loading={busy}
          loadingLabel={t("assessment.saving")}
        >
          {t("assessment.inputSave")}
        </Button>
      </div>
    </form>
  );
}

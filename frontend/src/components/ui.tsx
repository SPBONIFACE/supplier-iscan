// Shared components of the shell (design brief § 7.7 and 7.8): button, form field, message banner,
// loading indicator. Styles are in src/styles/base.css and use only var(--isc-...) tokens.
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, Ref } from "react";
import { useId } from "react";
import { useTranslation } from "react-i18next";

type ButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> & {
  variant?: "primary" | "secondary" | "text";
  /** Label shown while the action runs; the button becomes aria-disabled and keeps its width. */
  loading?: boolean;
  loadingLabel?: string;
  /** Visible reason when the button is disabled (linked by aria-describedby). */
  disabledReason?: string;
};

export function Button({
  variant = "primary",
  loading = false,
  loadingLabel,
  disabledReason,
  disabled,
  onClick,
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  const reasonId = useId();
  const inert = loading;
  return (
    <>
      <button
        {...rest}
        type={type}
        className={`btn btn-${variant}`}
        disabled={disabled}
        aria-disabled={inert || undefined}
        aria-describedby={disabled && disabledReason ? reasonId : rest["aria-describedby"]}
        aria-busy={loading || undefined}
        onClick={inert ? (event) => event.preventDefault() : onClick}
      >
        {loading && loadingLabel ? loadingLabel : children}
      </button>
      {disabled && disabledReason ? (
        <span id={reasonId} className="help">
          {disabledReason}
        </span>
      ) : null}
    </>
  );
}

type FormFieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "className" | "id"> & {
  label: string;
  /** Full message including its "Error:" prefix; marks the field invalid. */
  error?: string | null;
  help?: string;
  /** Shown after the field while a value is checked (aria-busy). */
  checking?: string;
  inputRef?: Ref<HTMLInputElement>;
};

export function FormField({ label, error, help, checking, inputRef, ...input }: FormFieldProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const helpId = `${id}-help`;
  const describedBy = [error ? errorId : null, help ? helpId : null].filter(Boolean).join(" ");
  return (
    <div className={error ? "fld err" : "fld"}>
      <label htmlFor={id}>{label}</label>
      <input
        {...input}
        id={id}
        ref={inputRef}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        aria-busy={checking ? true : undefined}
      />
      {checking ? <span className="help">{checking}</span> : null}
      {error ? (
        <span className="errmsg" id={errorId}>
          {error}
        </span>
      ) : null}
      {help ? (
        <span className="help" id={helpId}>
          {help}
        </span>
      ) : null}
    </div>
  );
}

type BannerProps = {
  kind: "error" | "note";
  children: ReactNode;
  /** Used to move focus to the banner after a failed submit. */
  bannerRef?: Ref<HTMLDivElement>;
};

/** System message: full width, 2px ink left rule, no fill. Errors are announced (role="alert"). */
export function MessageBanner({ kind, children, bannerRef }: BannerProps) {
  return (
    <div
      className="msg"
      role={kind === "error" ? "alert" : "status"}
      ref={bannerRef}
      tabIndex={kind === "error" ? -1 : undefined}
    >
      {children}
    </div>
  );
}

/** Text first, then static skeleton bars (decorative). */
export function LoadingIndicator() {
  const { t } = useTranslation();
  return (
    <div className="loading" role="status">
      <p>{t("common.loading")}</p>
      <div className="skeleton" aria-hidden="true" />
      <div className="skeleton short" aria-hidden="true" />
    </div>
  );
}

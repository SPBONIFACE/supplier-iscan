// Domain components of the supplier card (design brief § 7: status badge, fact row, source chip, quote
// block). #36, #37 and #38 reuse them. Everything that comes from a source or from the API is rendered
// as text, never as HTML; a link is opened only when its address is http or https.
import {
  Fragment,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { Trans, useTranslation } from "react-i18next";
import type { Fact } from "../lib/api";
import { formatDate } from "../lib/format";
import { hostOf, safeHttpUrl } from "../lib/safeUrl";
import { FactReviewBar, type ReviewControls } from "./FactReview";
import { NotePanel, NoteRef, useNotes } from "./notes";

/** Where the buyer can check a certificate when the API gives no more precise address. */
export const IAF_CERTSEARCH_URL = "https://www.iafcertsearch.org/";
const REDACTION = "[…]";

/** Text with each redaction mark set apart, so that an omission is visible and read as such. */
export function Redacted({ text }: { text: string }) {
  const { t } = useTranslation();
  const parts = text.split(REDACTION);
  return (
    <>
      {parts.map((part, position) => (
        <Fragment key={position}>
          {position > 0 ? (
            <span className="redact">
              {REDACTION}
              <span className="vh"> {t("card.redacted")}</span>
            </span>
          ) : null}
          {part}
        </Fragment>
      ))}
    </>
  );
}

/** The language of a quote, when the script tells it; the quote itself is never translated. */
export function quoteLanguage(text: string): string | undefined {
  if (/[぀-ヿ]/.test(text)) return "ja";
  if (/[가-힯]/.test(text)) return "ko";
  if (/[一-鿿]/.test(text)) return "zh";
  return undefined;
}

type BadgeStatus = Exclude<Fact["status"], "not_found">;

/** Fact status label: always a word, never colour alone. */
export function StatusBadge({ status }: { status: BadgeStatus }) {
  const { t } = useTranslation();
  return (
    <span className={status === "proposed" ? "badge badge--pending" : "badge badge--decided"}>
      {t(`card.status.${status}`)}
    </span>
  );
}

/** An external link that opens in a new tab, or the plain text when the address is not http or https. */
export function ExternalLink({
  href,
  children,
}: {
  href: string | null | undefined;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const safe = safeHttpUrl(href);
  if (!safe) return <span className="url">{children}</span>;
  return (
    <a className="url" href={safe} target="_blank" rel="noopener noreferrer">
      {children}
      <span className="vh"> {t("card.newTab")}</span>
    </a>
  );
}

/** The name of the source of a fact: the publisher, else the host of its address. */
export const sourceName = (fact: Fact): string =>
  fact.publisher ?? hostOf(fact.source_url) ?? fact.source_url ?? "";

type ChipProps = {
  fact: Fact;
  /** Shorter text for the key-figures band. */
  compact?: boolean;
  noteId: string;
  open: boolean;
  onToggle: () => void;
  chipRef?: Ref<HTMLButtonElement>;
};

/** The button that reveals the Quote of a fact. Enter and Space (native button) open and close it. */
export function SourceChip({ fact, compact = false, noteId, open, onToggle, chipRef }: ChipProps) {
  const { i18n } = useTranslation();
  const date = fact.fetched_at ? formatDate(fact.fetched_at, i18n.language) : "";
  return (
    <button
      type="button"
      className="chip"
      ref={chipRef}
      aria-expanded={open}
      aria-controls={noteId}
      onClick={onToggle}
      onKeyDown={(event) => {
        if (open && event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation(); // closes the quote, not the panel
          onToggle();
        }
      }}
    >
      {compact ? (
        <span>
          {sourceName(fact)} · {date}
        </span>
      ) : (
        <span>
          <Trans
            i18nKey="card.foundIn"
            values={{ source: sourceName(fact), date }}
            components={{ cite: <cite className="src-name" /> }}
          />
        </span>
      )}
      <span className="chip-ind" aria-hidden="true">
        {open ? "−" : "+"}
      </span>
    </button>
  );
}

export function SourceTypeLabel({ type }: { type: Fact["source_type"] }) {
  const { t } = useTranslation();
  return type ? <span className="ev">{t(`card.sourceType.${type}`)}</span> : null;
}

type QuoteProps = {
  fact: Fact;
  fieldLabel: string;
  noteId: string;
  onClose: () => void;
  headingRef: Ref<HTMLHeadingElement>;
  /** Marks the note under the key-figures band rather than under a row. */
  band?: boolean;
  /** The note number of the source on the card page; the quote then links to its entry in Sources. */
  noteNumber?: number | null;
};

/** The Quote of a fact, verbatim and in its source language, with its attribution. */
export function QuoteBlock({
  fact,
  fieldLabel,
  noteId,
  onClose,
  headingRef,
  band = false,
  noteNumber = null,
}: QuoteProps) {
  const { t, i18n } = useTranslation();
  const headingId = useId();
  const quote = fact.quote ?? "";
  const link = safeHttpUrl(fact.source_url);
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation(); // closes the quote, not the panel
      onClose();
    }
  };
  return (
    <section
      className={band ? "note kf-note" : "note"}
      id={noteId}
      aria-labelledby={headingId}
      onKeyDown={onKeyDown}
    >
      <div className="note-head">
        <h4 className="note-title" id={headingId} ref={headingRef} tabIndex={-1}>
          {t(fact.status === "corrected" ? "card.quoteTitleOriginal" : "card.quoteTitle", {
            field: fieldLabel,
          })}
        </h4>
        <button type="button" className="btn-text disclosure btn-close-note" onClick={onClose}>
          {t("card.closeQuote")}
        </button>
      </div>
      <blockquote className="quote" lang={quoteLanguage(quote)} dir="auto" cite={link ?? undefined}>
        <Redacted text={quote} />
      </blockquote>
      <div className="quote-src">
        <p>
          <Trans
            i18nKey="card.foundIn"
            values={{
              source: sourceName(fact),
              date: fact.fetched_at ? formatDate(fact.fetched_at, i18n.language) : "",
            }}
            components={{ cite: <cite className="src-name" /> }}
          />
        </p>
        {noteNumber ? (
          <p className="note-link">
            <a href={`#n${noteNumber}`}>{t("card.noteInSources", { number: noteNumber })}</a>
          </p>
        ) : null}
        <div className="labels">
          <SourceTypeLabel type={fact.source_type} />
          {fact.quote_redacted ? <span className="ev">{t("card.redactedExtract")}</span> : null}
        </div>
        <dl className="attr">
          {fact.author ? (
            <>
              <dt>{t("card.author")}</dt>
              <dd>
                <Redacted text={fact.author} />
              </dd>
            </>
          ) : null}
          {fact.publisher ? (
            <>
              <dt>{t("card.publisher")}</dt>
              <dd>{fact.publisher}</dd>
            </>
          ) : null}
          {fact.source_url ? (
            <>
              <dt>{t("card.url")}</dt>
              <dd>
                <ExternalLink href={fact.source_url}>{fact.source_url}</ExternalLink>
              </dd>
            </>
          ) : null}
          {fact.fetched_at ? (
            <>
              <dt>{t("card.date")}</dt>
              <dd>{formatDate(fact.fetched_at, i18n.language)}</dd>
            </>
          ) : null}
        </dl>
      </div>
    </section>
  );
}

/** Opens and closes the quote of one fact and keeps keyboard focus where the buyer expects it. */
export function useQuoteToggle() {
  const [open, setOpen] = useState(false);
  const chip = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const opened = useRef(false);
  useEffect(() => {
    if (open) heading.current?.focus();
    else if (opened.current) chip.current?.focus();
    opened.current = open;
  }, [open]);
  return {
    open,
    chip,
    heading,
    toggle: () => setOpen((value) => !value),
    close: () => setOpen(false),
  };
}

type FactRowProps = {
  label: string;
  fact: Fact | null;
  /** The run stopped before this field: it was not examined, which is not "No public evidence found". */
  notCovered?: boolean;
  concernsPeople?: boolean;
  certification?: boolean;
  /** Roving tab stop of the list the row belongs to (see FactList). */
  nav?: RowNav;
  /** Review actions (#36); without them the row is read-only. */
  review?: ReviewControls;
};

/** The roving tab stop of one row of a FactList. */
export type RowNav = { tabIndex: 0 | -1; onFocus: () => void };

/**
 * The facts of one section: one Tab stop for the list, Up and Down arrows (and Home, End) move from row
 * to row (mock-up 05-review-default). `children` receives a function giving each row its tab stop.
 */
export function FactList({
  label,
  children,
}: {
  label: string;
  children: (nav: (index: number) => RowNav) => ReactNode;
}) {
  const [active, setActive] = useState(0);
  const list = useRef<HTMLUListElement>(null);
  const nav = (index: number): RowNav => ({
    tabIndex: index === active ? 0 : -1,
    onFocus: () => setActive(index),
  });
  const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    const rows = Array.from(list.current?.children ?? []) as HTMLElement[];
    const at = rows.indexOf(event.target as HTMLElement); // only when a row itself has the focus
    if (at < 0 || rows.length === 0) return;
    const to =
      event.key === "ArrowDown"
        ? Math.min(at + 1, rows.length - 1)
        : event.key === "ArrowUp"
          ? Math.max(at - 1, 0)
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? rows.length - 1
              : -1;
    if (to < 0) return;
    event.preventDefault();
    rows[to]?.focus();
  };
  return (
    <ul className="facts" aria-label={label} ref={list} onKeyDown={onKeyDown}>
      {children(nav)}
    </ul>
  );
}

/** One field of the profile: its value, status and source chip, or "No public evidence found". */
export function FactRow({
  label,
  fact,
  notCovered = false,
  concernsPeople = false,
  certification = false,
  nav,
  review,
}: FactRowProps) {
  const { t } = useTranslation();
  const base = useId();
  const labelId = `${base}-label`;
  const noteId = `${base}-note`;
  const quote = useQuoteToggle();
  const notes = useNotes();
  const row = useRef<HTMLLIElement>(null);
  const evidence = fact && fact.status !== "not_found" ? fact : null;
  const verify = certification
    ? (safeHttpUrl(fact?.verification_url ?? null) ?? IAF_CERTSEARCH_URL)
    : null;
  if (notes) {
    // The card page: a ledger line, field, value with its note number, then the review column.
    const slot = `row-${fact?.id ?? base}`;
    return (
      <li
        className="fact fact-ledger"
        id={fact ? `fact-${fact.id}` : undefined}
        aria-labelledby={labelId}
        ref={row}
        tabIndex={nav?.tabIndex}
        onFocus={nav?.onFocus}
      >
        <span className="f-label" id={labelId}>
          {label}
          {concernsPeople ? <span className="f-hint">{t("card.aboutPeople")}</span> : null}
        </span>
        <div className="f-main">
          {notCovered ? (
            <span className="not-covered-field">{t("card.notCoveredField")}</span>
          ) : evidence ? (
            <>
              <span className="f-value">
                <Redacted text={evidence.value ?? ""} />
              </span>
              <NoteRef fact={evidence} slot={slot} field={label} />
              {evidence.status === "corrected" && evidence.original_value ? (
                <span className="f-original">
                  {t("card.originalValue")} <Redacted text={evidence.original_value} />
                </span>
              ) : null}
              <span className="f-src">
                <SourceTypeLabel type={evidence.source_type} />
                {evidence.quote_redacted ? <RedactedLabel /> : null}
              </span>
            </>
          ) : (
            <span className="missing">{t("card.noEvidence")}</span>
          )}
          {verify ? (
            <p className="f-cert">
              <ExternalLink href={verify}>{t("card.verifyIaf")}</ExternalLink>
            </p>
          ) : null}
        </div>
        {evidence ? (
          <div className="f-rev">
            <StatusBadge status={evidence.status as BadgeStatus} />
            {review ? (
              <FactReviewBar
                fact={evidence}
                label={label}
                review={review}
                focusRow={() => row.current?.focus()}
              />
            ) : null}
          </div>
        ) : null}
        {evidence ? <NotePanel fact={evidence} slot={slot} field={label} /> : null}
      </li>
    );
  }
  return (
    <li
      className="fact"
      id={fact ? `fact-${fact.id}` : undefined}
      aria-labelledby={labelId}
      ref={row}
      tabIndex={nav?.tabIndex}
      onFocus={nav?.onFocus}
    >
      <span className="f-label" id={labelId}>
        {label}
        {concernsPeople ? <span className="f-hint">{t("card.aboutPeople")}</span> : null}
      </span>
      <div className="f-main">
        {notCovered ? (
          <span className="not-covered-field">{t("card.notCoveredField")}</span>
        ) : evidence ? (
          <>
            <div className="f-line">
              <span className="f-value">
                <Redacted text={evidence.value ?? ""} />
              </span>
              <span className="f-status">
                <StatusBadge status={evidence.status as BadgeStatus} />
              </span>
            </div>
            {evidence.quote === null ? null : evidence.status === "corrected" &&
              evidence.original_value ? (
              <div className="f-original">
                <span>
                  {t("card.originalValue")} <Redacted text={evidence.original_value} />
                </span>
                <Chip row={evidence} noteId={noteId} quote={quote} />
              </div>
            ) : (
              <Chip row={evidence} noteId={noteId} quote={quote} />
            )}
          </>
        ) : (
          <span className="missing">{t("card.noEvidence")}</span>
        )}
        {verify ? (
          <p className="f-cert">
            <ExternalLink href={verify}>{t("card.verifyIaf")}</ExternalLink>
          </p>
        ) : null}
        {review && evidence ? (
          <FactReviewBar
            fact={evidence}
            label={label}
            review={review}
            focusRow={() => row.current?.focus()}
          />
        ) : null}
      </div>
      {evidence && quote.open && evidence.quote ? (
        <QuoteBlock
          fact={evidence}
          fieldLabel={label}
          noteId={noteId}
          onClose={quote.close}
          headingRef={quote.heading}
        />
      ) : null}
    </li>
  );
}

function Chip({
  row,
  noteId,
  quote,
}: {
  row: Fact;
  noteId: string;
  quote: ReturnType<typeof useQuoteToggle>;
}) {
  return (
    <div className="f-src">
      <SourceChip
        fact={row}
        noteId={noteId}
        open={quote.open}
        onToggle={quote.toggle}
        chipRef={quote.chip}
      />
      <SourceTypeLabel type={row.source_type} />
      {row.quote_redacted ? <RedactedLabel /> : null}
    </div>
  );
}

function RedactedLabel() {
  const { t } = useTranslation();
  return <span className="ev">{t("card.redactedExtract")}</span>;
}

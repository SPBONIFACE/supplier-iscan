// Note numbers of the supplier card page (tearsheet card, #163). Each shown fact value carries a
// superscript number, given per source; activating it opens the quote under the value. One quote is open
// at a time; Esc closes it and the focus returns to the number. Outside the card page there is no
// provider, and the facts keep their source chip.
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import type { Fact } from "../lib/api";
import type { NoteIndex } from "../lib/notes";
import { QuoteBlock } from "./evidence";

type NotesApi = {
  index: NoteIndex;
  openSlot: string | null;
  toggle: (slot: string) => void;
  close: () => void;
  register: (slot: string, node: HTMLButtonElement | null) => void;
};

const NotesContext = createContext<NotesApi | null>(null);

/** The notes of the card page, or null where facts are shown with a source chip. */
export const useNotes = (): NotesApi | null => useContext(NotesContext);

export function NotesProvider({ index, children }: { index: NoteIndex; children: ReactNode }) {
  const [openSlot, setOpenSlot] = useState<string | null>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const previous = useRef<string | null>(null);

  // When a quote closes, the focus returns to the number that opened it.
  useEffect(() => {
    if (previous.current && openSlot === null) buttons.current.get(previous.current)?.focus();
    previous.current = openSlot;
  }, [openSlot]);

  const toggle = useCallback(
    (slot: string) => setOpenSlot((now) => (now === slot ? null : slot)),
    [],
  );
  const close = useCallback(() => setOpenSlot(null), []);
  const register = useCallback((slot: string, node: HTMLButtonElement | null) => {
    if (node) buttons.current.set(slot, node);
    else buttons.current.delete(slot);
  }, []);
  const api = useMemo(
    () => ({ index, openSlot, toggle, close, register }),
    [index, openSlot, toggle, close, register],
  );
  return <NotesContext.Provider value={api}>{children}</NotesContext.Provider>;
}

/** The superscript number of a fact's source, as a button that opens its quote under the value. */
export function NoteRef({ fact, slot, field }: { fact: Fact; slot: string; field: string }) {
  const { t } = useTranslation();
  const notes = useNotes();
  const number = notes?.index.numberOf(fact) ?? null;
  if (!notes || number === null) return null;
  const open = notes.openSlot === slot;
  return (
    <sup className="note-ref">
      <button
        type="button"
        ref={(node) => notes.register(slot, node)}
        aria-expanded={open}
        aria-controls={`${slot}-quote`}
        aria-label={t("card.noteRef", { number, field })}
        onClick={() => notes.toggle(slot)}
        onKeyDown={(event) => {
          if (open && event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation(); // closes the quote, not the page
            notes.close();
          }
        }}
      >
        {number}
      </button>
    </sup>
  );
}

/** The quote under a value, when its number is open. */
export function NotePanel({ fact, slot, field }: { fact: Fact; slot: string; field: string }) {
  const notes = useNotes();
  const heading = useRef<HTMLHeadingElement>(null);
  const open = notes?.openSlot === slot;
  useEffect(() => {
    if (open) heading.current?.focus();
  }, [open]);
  if (!notes || !open || !fact.quote) return null;
  return (
    <QuoteBlock
      fact={fact}
      fieldLabel={field}
      noteId={`${slot}-quote`}
      onClose={notes.close}
      headingRef={heading}
      noteNumber={notes.index.numberOf(fact)}
    />
  );
}

// Loads the assessment of a run and keeps it fresh (#37). While a drafting job is queued or running
// (`pending`), or a requested drafting has not shown up yet, the endpoint is read again at a configured
// interval. Nothing here drafts anything by itself: the member presses "Draft" or "Redraft".
import { useCallback, useEffect, useRef, useState } from "react";
import {
  type Assessment,
  type AssessmentStatement,
  api,
  type BuyerInputs,
  type DraftingPart,
} from "./api";
import { assessmentPollIntervalMs } from "./config";

export type AssessmentLoad = "loading" | "ready" | "not_found" | "error";
/** What happened to a drafting the member asked for. */
export type DraftingOutcome = "done" | "nothing_new" | null;

export const RECOMMENDATION_KINDS: readonly AssessmentStatement["kind"][] = [
  "procurement_implication",
  "relationship_level",
  "contract_approach",
  "volume_share",
  "next_action",
  "procurement_priority",
];

const kindsOf = (part: DraftingPart): readonly AssessmentStatement["kind"][] =>
  part === "fit" ? ["fit"] : RECOMMENDATION_KINDS;

const latestDraft = (items: AssessmentStatement[], part: DraftingPart): string | null =>
  items
    .filter((item) => kindsOf(part).includes(item.kind))
    .map((item) => item.provenance.generated_at)
    .sort()
    .at(-1) ?? null;

export function useAssessment(runId: string, enabled: boolean) {
  const [load, setLoad] = useState<AssessmentLoad>("loading");
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [inputs, setInputs] = useState<BuyerInputs | null>(null);
  const [outcome, setOutcome] = useState<Record<DraftingPart, DraftingOutcome>>({
    fit: null,
    recommendations: null,
  });
  // Drafting the member asked for: the newest draft there was before, to tell "done" from "nothing new".
  const asked = useRef(new Map<DraftingPart, string | null>());
  const [waiting, setWaiting] = useState<DraftingPart[]>([]);
  const sequence = useRef(0);
  const current = useRef<Assessment | null>(null);

  const read = useCallback(
    async (withInputs = true) => {
      const mine = ++sequence.current;
      const [a, i] = await Promise.all([
        api.getRunAssessment(runId),
        withInputs ? api.getRunBuyerInputs(runId) : Promise.resolve(null),
      ]);
      if (mine !== sequence.current) return;
      if (!a.ok) {
        if (a.kind === "not_found") return setLoad("not_found");
        if (a.kind === "unauthorized") return;
        return setLoad((was) => (was === "ready" ? was : "error"));
      }
      if (i && !i.ok) {
        if (i.kind === "unauthorized") return;
        return setLoad((was) =>
          was === "ready" ? was : i.kind === "not_found" ? "not_found" : "error",
        );
      }
      current.current = a.data;
      setAssessment(a.data);
      if (i) setInputs(i.data);
      setLoad("ready");
      // A drafting that is no longer pending is over.
      for (const [part, before] of [...asked.current]) {
        if (a.data.pending.includes(part)) continue;
        const after = latestDraft(a.data.items, part);
        asked.current.delete(part);
        setOutcome((was) => ({
          ...was,
          [part]: after && after !== before ? "done" : "nothing_new",
        }));
      }
      setWaiting([...asked.current.keys()]);
    },
    [runId],
  );

  useEffect(() => {
    if (!enabled) return;
    setLoad("loading");
    void read();
    return () => {
      sequence.current++;
    };
  }, [enabled, read]);

  const polling =
    enabled &&
    load === "ready" &&
    (assessment?.status === "pending" ||
      (assessment?.pending.length ?? 0) > 0 ||
      waiting.length > 0);
  useEffect(() => {
    if (!polling) return;
    const timer = window.setTimeout(() => void read(false), assessmentPollIntervalMs());
    return () => window.clearTimeout(timer);
  }, [polling, read, assessment, waiting]);

  /** The member asked for a drafting and the server queued it: follow it until it is over. */
  const startDrafting = useCallback(
    (part: DraftingPart) => {
      asked.current.set(part, latestDraft(current.current?.items ?? [], part));
      setWaiting([...asked.current.keys()]);
      setOutcome((was) => ({ ...was, [part]: null }));
      void read(false);
    },
    [read],
  );

  /** Puts a statement as the server returned it; a deleted one leaves the list. */
  const applyStatement = useCallback((statement: AssessmentStatement) => {
    setAssessment((was) => {
      if (!was) return was;
      const items =
        statement.provenance.status === "deleted"
          ? was.items.filter((item) => item.id !== statement.id)
          : was.items.map((item) => (item.id === statement.id ? statement : item));
      current.current = { ...was, items };
      return current.current;
    });
  }, []);

  return {
    load,
    assessment,
    inputs,
    outcome,
    drafting: waiting,
    reload: () => void read(),
    /** Reads the criteria, buyer context and buyer inputs again (after a save or a conflict). */
    reloadInputs: async () => {
      const result = await api.getRunBuyerInputs(runId);
      if (result.ok) setInputs(result.data);
    },
    startDrafting,
    applyStatement,
  };
}

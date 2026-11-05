// Loads what the supplier card shows: the run (header, flags), its facts and the profile definition
// (sections and labels in the UI language). Nothing is polled: a run that is not over has no card.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Fact, type Language, type ProfileDefinition, type Run } from "./api";

export type CardData = { run: Run; facts: Fact[]; definition: ProfileDefinition };
export type CardLoad = "loading" | "ready" | "not_found" | "error";

/** Whether a run has produced a profile (a complete or a partial one). */
export const hasProfile = (run: Run): boolean =>
  run.status === "completed" || run.status === "partial";

export function useRunCard(id: string, language: Language) {
  const [load, setLoad] = useState<CardLoad>("loading");
  const [data, setData] = useState<CardData | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const sequence = useRef(0);

  const start = useCallback(async () => {
    const mine = ++sequence.current;
    setLoad("loading");
    const runResult = await api.getRun(id);
    if (mine !== sequence.current) return;
    if (!runResult.ok) {
      if (runResult.kind === "not_found") return setLoad("not_found");
      if (runResult.kind === "unauthorized") return; // the shell sends the member to sign in
      return setLoad("error");
    }
    setRun(runResult.data);
    if (!hasProfile(runResult.data)) {
      setData(null);
      return setLoad("ready");
    }
    const [facts, definition] = await Promise.all([
      api.listRunFacts(id),
      api.getProfileDefinition(language),
    ]);
    if (mine !== sequence.current) return;
    if (!facts.ok || !definition.ok) {
      if (!facts.ok && facts.kind === "not_found") return setLoad("not_found");
      if (!facts.ok && facts.kind === "unauthorized") return;
      return setLoad("error");
    }
    setData({ run: runResult.data, facts: facts.data.items, definition: definition.data });
    setLoad("ready");
  }, [id, language]);

  useEffect(() => {
    void start();
    return () => {
      sequence.current++; // a left card needs no answer
    };
  }, [start]);

  return { load, run, data, retry: () => void start() };
}

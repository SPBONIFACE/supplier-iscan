// Loads what the comparison shows (spec F5): the runs with their facts, the profile definition (sections and
// labels in the UI language) and the organisation (its name, and the maximum number of profiles). Nothing
// is polled: a run still going shows "run in progress" in its column.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type ComparisonRun,
  type Language,
  type MemberOrganisation,
  type ProfileDefinition,
} from "./api";

export type ComparisonData = {
  items: ComparisonRun[];
  definition: ProfileDefinition;
  organisation: MemberOrganisation | null;
};
export type ComparisonLoad =
  | { kind: "loading" }
  | { kind: "ready"; data: ComparisonData }
  | { kind: "not_found" }
  | { kind: "range"; maximum: number | null }
  | { kind: "error" };

/** The run ids of the URL (`?runs=a,b`), without blanks or duplicates, in the order given. */
export function parseRunIds(raw: string | null): string[] {
  return Array.from(
    new Set(
      (raw ?? "")
        .split(",")
        .map((id) => id.trim())
        .filter((id) => id.length > 0),
    ),
  );
}

export function useComparison(ids: string[], language: Language) {
  const [load, setLoad] = useState<ComparisonLoad>({ kind: "loading" });
  const sequence = useRef(0);
  const key = ids.join(",");

  const start = useCallback(async () => {
    const mine = ++sequence.current;
    const wanted = key ? key.split(",") : [];
    // Fewer than two ids is answered on the screen, without a call.
    if (wanted.length < 2) return setLoad({ kind: "range", maximum: null });
    setLoad({ kind: "loading" });
    const [comparison, definition, organisation] = await Promise.all([
      api.getComparison(wanted),
      api.getProfileDefinition(language),
      api.getOrganisation(),
    ]);
    if (mine !== sequence.current) return;
    if (!comparison.ok) {
      if (comparison.kind === "unauthorized") return; // the shell sends the member to sign in
      if (comparison.kind === "not_found") return setLoad({ kind: "not_found" });
      if (comparison.kind === "validation") {
        return setLoad({
          kind: "range",
          maximum: organisation.ok ? organisation.data.comparison_max_profiles : null,
        });
      }
      return setLoad({ kind: "error" });
    }
    if (!definition.ok) {
      return definition.kind === "unauthorized" ? undefined : setLoad({ kind: "error" });
    }
    setLoad({
      kind: "ready",
      data: {
        items: comparison.data.items,
        definition: definition.data,
        organisation: organisation.ok ? organisation.data : null,
      },
    });
  }, [key, language]);

  useEffect(() => {
    void start();
    return () => {
      sequence.current++; // a left screen needs no answer
    };
  }, [start]);

  return { load, retry: () => void start() };
}

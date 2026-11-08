// Loads a run with its failure log and source count, and keeps them current by polling while the run is
// queued, running or paused. Polling stops at a final state and when the screen is left.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Run, type RunFailure, type RunStatus } from "./api";
import { runPollIntervalMs } from "./config";

/** The states in which the run still changes by itself (or by the member's Resume). */
export const ACTIVE_STATUSES: RunStatus[] = ["queued", "running", "paused"];
export const isActive = (status: RunStatus): boolean => ACTIVE_STATUSES.includes(status);

export type RunProgress = {
  run: Run;
  /** Null when the log could not be read yet: the screen says so rather than "no failures". */
  failures: RunFailure[] | null;
  sourceCount: number | null;
};

export type RunLoad = "loading" | "ready" | "not_found" | "error";

export function useRunProgress(id: string) {
  const [load, setLoad] = useState<RunLoad>("loading");
  const [data, setData] = useState<RunProgress | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const alive = useRef(true);
  const sequence = useRef(0);
  const hasData = useRef(false);

  const refresh = useCallback(async () => {
    const mine = ++sequence.current;
    const [run, failures, sources] = await Promise.all([
      api.getRun(id),
      api.listRunFailures(id),
      api.listRunSources(id),
    ]);
    // A newer read or an action's answer supersedes this one; a left screen needs none.
    if (!alive.current || mine !== sequence.current) return;
    if (!run.ok) {
      if (run.kind === "not_found") return setLoad("not_found");
      if (run.kind === "unauthorized") return; // the shell sends the member to sign in
      setUnreachable(true);
      if (!hasData.current) setLoad("error");
      return;
    }
    setUnreachable(false);
    hasData.current = true;
    setData((previous) => ({
      run: run.data,
      failures: failures.ok ? failures.data.items : (previous?.failures ?? null),
      sourceCount: sources.ok ? sources.data.items.length : (previous?.sourceCount ?? null),
    }));
    setLoad("ready");
  }, [id]);

  const start = useCallback(() => {
    hasData.current = false;
    setLoad("loading");
    setData(null);
    setUnreachable(false);
    void refresh();
  }, [refresh]);

  useEffect(() => {
    alive.current = true;
    start();
    return () => {
      alive.current = false;
    };
  }, [start]);

  const status = data?.run.status;
  const active = status !== undefined && isActive(status);
  const wasActive = useRef(false);

  useEffect(() => {
    if (!active) return;
    const interval = runPollIntervalMs();
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = () => {
      timer = setTimeout(async () => {
        await refresh();
        if (!stopped) schedule();
      }, interval);
    };
    schedule();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [active, refresh]);

  // One last read when the run ends, so the failure log is complete.
  useEffect(() => {
    if (wasActive.current && !active) void refresh();
    wasActive.current = active;
  }, [active, refresh]);

  /** Shows the run returned by Stop or Resume at once and drops any read still in flight. */
  const apply = useCallback((run: Run) => {
    sequence.current++;
    setData((previous) => (previous ? { ...previous, run } : previous));
  }, []);

  return { load, data, unreachable, refresh, retry: start, apply };
}

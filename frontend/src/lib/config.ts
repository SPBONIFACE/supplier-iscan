// Frontend configuration values read from the build environment (never secrets).
const DEFAULT_RUN_POLL_MS = 3000;
const MIN_RUN_POLL_MS = 100;

/** Milliseconds between two reads of a run that is queued, running or paused. */
export function runPollIntervalMs(): number {
  const value = Number(import.meta.env.VITE_RUN_POLL_INTERVAL_MS);
  return Number.isFinite(value) && value >= MIN_RUN_POLL_MS ? value : DEFAULT_RUN_POLL_MS;
}

const DEFAULT_ASSESSMENT_POLL_MS = 3000;

/** Milliseconds between two reads of an assessment while a drafting is queued or running. */
export function assessmentPollIntervalMs(): number {
  const value = Number(import.meta.env.VITE_ASSESSMENT_POLL_INTERVAL_MS);
  return Number.isFinite(value) && value >= MIN_RUN_POLL_MS ? value : DEFAULT_ASSESSMENT_POLL_MS;
}

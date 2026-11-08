/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the API; defaults to http://localhost:8000 (local development). */
  readonly VITE_API_BASE_URL?: string;
  /** Interval in milliseconds between two reads of a run still going; 3000 when absent. */
  readonly VITE_RUN_POLL_INTERVAL_MS?: string;
}

/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the API; defaults to http://localhost:8000 (local development). */
  readonly VITE_API_BASE_URL?: string;
}

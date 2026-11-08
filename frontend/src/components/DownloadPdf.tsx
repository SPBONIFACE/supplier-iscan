// "Download PDF" on the supplier card (spec F9): the server builds the file in the UI language; the button
// shows a generating state, is disabled while the request runs, and reports a failure in plain words.
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import { Button } from "./ui";

type Props = {
  runId: string;
  /** Why the file cannot be made now (the run is still going): the button is disabled and says so. */
  unavailableReason?: string;
  /** The id is a demo profile's: the public demo route builds the file (#50). */
  demo?: boolean;
};

/** Hands a downloaded file to the browser. Only a blob URL of our own response is used. */
function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function DownloadPdf({ runId, unavailableReason, demo = false }: Props) {
  const { t, i18n } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<"error" | "in_progress" | null>(null);
  const [done, setDone] = useState(false);
  const button = useRef<HTMLDivElement>(null);

  if (unavailableReason) {
    return (
      <div className="pdf-action">
        <Button variant="secondary" disabled disabledReason={unavailableReason}>
          {t("pdf.download")}
        </Button>
      </div>
    );
  }

  const run = async () => {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    setDone(false);
    const language = i18n.language === "fr" ? "fr" : "en";
    const result = await (demo
      ? api.downloadDemoProfilePdf(runId, language)
      : api.downloadRunPdf(runId, language));
    setBusy(false);
    if (result.ok) {
      save(result.data.blob, result.data.filename);
      setDone(true);
      return;
    }
    if (result.kind === "unauthorized") return; // the shell sends the member to sign in
    setProblem(result.kind === "conflict" ? "in_progress" : "error");
  };

  return (
    <div className="pdf-action" ref={button}>
      <Button
        variant="secondary"
        loading={busy}
        loadingLabel={t("pdf.generating")}
        onClick={() => void run()}
      >
        {t("pdf.download")}
      </Button>
      <span className="vh" role="status">
        {busy ? t("pdf.generating") : done ? t("pdf.ready") : ""}
      </span>
      {problem ? (
        <p className="errmsg" role="alert">
          {t(problem === "in_progress" ? "pdf.inProgress" : "pdf.error")}
        </p>
      ) : null}
    </div>
  );
}

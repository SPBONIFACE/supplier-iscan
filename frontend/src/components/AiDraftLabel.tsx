// The AI-draft label (design brief § 6 and 7.6): "AI draft, pending your validation" exactly while a
// statement is an `ai_draft`; once a member decides, the review status replaces it. #39 mirrors it in the PDF.
// Always a word, never colour alone. A statement written by rules (the financial guidance) is not an AI
// draft, so it reads "Pending your validation".
import { useTranslation } from "react-i18next";

export type DraftStatus = "ai_draft" | "approved" | "corrected" | "deleted";

export function AiDraftLabel({
  status,
  byRules = false,
}: {
  status: DraftStatus;
  byRules?: boolean;
}) {
  const { t } = useTranslation();
  if (status === "ai_draft") {
    return (
      <span className="badge badge--pending">
        {byRules ? t("assessment.pendingRules") : t("assessment.aiDraft")}
      </span>
    );
  }
  return (
    <span className={status === "deleted" ? "badge badge--deleted" : "badge badge--decided"}>
      {t(`assessment.status.${status}`)}
    </span>
  );
}

import { useTranslation } from "react-i18next";
import type { IdentityCandidate } from "../lib/api";

/** A candidate as in the approved mock-up: name, website, country, sector, description, sources. */
export function CandidateCard({
  candidate,
  title,
  record = false,
}: {
  candidate: IdentityCandidate;
  title?: string;
  /** The identity record shown before confirmation: adds legal form and registry identifiers. */
  record?: boolean;
}) {
  const { t } = useTranslation();
  const none = t("identity.notGiven");
  return (
    <section className="cand" aria-label={title ?? candidate.legal_name}>
      <h3>{title ?? candidate.legal_name}</h3>
      <dl className="dl">
        {record ? (
          <>
            <dt>{t("identity.legalName")}</dt>
            <dd>{candidate.legal_name}</dd>
            <dt>{t("identity.legalForm")}</dt>
            <dd>{candidate.legal_form ?? none}</dd>
          </>
        ) : null}
        <dt>{t("identity.website")}</dt>
        <dd className="mono">{candidate.website ?? none}</dd>
        <dt>{t("identity.country")}</dt>
        <dd>{candidate.country ?? none}</dd>
        <dt>{t("identity.sector")}</dt>
        <dd>{candidate.sector ?? none}</dd>
        {record ? null : (
          <>
            <dt>{t("identity.description")}</dt>
            <dd>{candidate.description ?? none}</dd>
          </>
        )}
        {record ? (
          <>
            <dt>{t("identity.identifiers")}</dt>
            <dd className="mono">
              {candidate.identifiers.length
                ? candidate.identifiers.map((id) => `${id.scheme} ${id.value}`).join(", ")
                : none}
            </dd>
          </>
        ) : null}
      </dl>
      {candidate.found_in.length ? (
        <p className="srcline">
          {t("identity.foundIn", {
            sources: candidate.found_in.map((s) => t(`identity.source.${s}`)).join(", "),
          })}
        </p>
      ) : null}
    </section>
  );
}

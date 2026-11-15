import { useTranslation } from "react-i18next";
import type { IdentityCandidate } from "../lib/api";
import { countryName } from "../lib/format";

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
  const { t, i18n } = useTranslation();
  const none = t("identity.notGiven");
  // A value filled from the buyer's hints is labelled as such, never as found in a source (#187).
  const given = (field: "country" | "sector") =>
    candidate.given_by_buyer.includes(field) ? ` (${t("identity.givenByYou")})` : "";
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
        <dd>
          {candidate.country ? countryName(candidate.country, i18n.language) : none}
          {given("country")}
        </dd>
        <dt>{t("identity.sector")}</dt>
        <dd>
          {candidate.sector ?? none}
          {given("sector")}
        </dd>
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

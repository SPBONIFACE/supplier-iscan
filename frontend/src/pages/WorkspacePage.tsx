// The workspace (spec Flow 1, F5, F7; mock-ups 04-profile-list-*): the organisation's profile runs, the
// remaining quota, the entry to a new profile and the selection for comparison.
import { useCallback, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useMatch, useNavigate } from "react-router";
import { LoadingIndicator, MessageBanner } from "../components/ui";
import { api, type MemberOrganisation, type Run } from "../lib/api";
import { formatDate, formatNumber } from "../lib/format";
import { useTitle } from "../lib/useTitle";

// Only a run that produced a profile has a supplier card and can be compared.
const HAS_PROFILE = ["partial", "completed"];
const MAX_COMPARED = 20; // technical bound on the URL; the comparison (#38) applies the product maximum

const lastUpdated = (run: Run): string => run.finished_at ?? run.started_at ?? run.created_at;

type Loaded = { runs: Run[]; organisation: MemberOrganisation | null };
type State = { kind: "loading" } | { kind: "error" } | ({ kind: "ready" } & Loaded);

export function WorkspacePage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  // The card open beside the list (route /profiles/:profileId), to mark its row.
  const openRun = useMatch("/profiles/:profileId")?.params.profileId ?? null;
  const [state, setState] = useState<State>({ kind: "loading" });
  const [selected, setSelected] = useState<string[]>([]);
  const refusalId = useId();
  const compareWhyId = useId();
  useTitle(t("workspace.title"));

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    const [runs, organisation] = await Promise.all([api.listRuns(), api.getOrganisation()]);
    // 401 is handled by the shell (redirect to sign-in); any other failure of the list is shown here.
    if (!runs.ok) return setState({ kind: "error" });
    // Without the organisation the list still works; quota and refusal are shown only when known.
    setState({
      kind: "ready",
      runs: runs.data.items,
      organisation: organisation.ok ? organisation.data : null,
    });
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (state.kind === "loading") {
    return (
      <>
        <h1>{t("workspace.title")}</h1>
        <LoadingIndicator />
      </>
    );
  }
  if (state.kind === "error") {
    return (
      <>
        <h1>{t("workspace.title")}</h1>
        <MessageBanner kind="error">
          <p>{t("workspace.loadError")}</p>
          <p>
            <button type="button" className="btn btn-secondary" onClick={() => void load()}>
              {t("common.retry")}
            </button>
          </p>
        </MessageBanner>
      </>
    );
  }

  const { runs, organisation } = state;
  const refusal = organisation?.run_refusal_reason ?? null;
  const refused = refusal !== null;
  const canCompare = selected.length >= 2;
  const accessEnd = organisation?.access_ends_at
    ? formatDate(organisation.access_ends_at, i18n.language)
    : null;

  const toggle = (id: string) =>
    setSelected((current) =>
      current.includes(id)
        ? current.filter((other) => other !== id)
        : current.length >= MAX_COMPARED
          ? current
          : [...current, id],
    );
  const compare = () => {
    if (canCompare) navigate(`/compare?runs=${selected.map(encodeURIComponent).join(",")}`);
  };

  const meta: string[] = [];
  if (organisation) {
    meta.push(organisation.name);
    meta.push(
      organisation.profiles_remaining === null
        ? t("workspace.quotaUnlimited")
        : organisation.profile_quota === null
          ? t("workspace.quotaRemaining", {
              remaining: formatNumber(organisation.profiles_remaining, i18n.language),
            })
          : t("workspace.quotaRemainingOf", {
              remaining: formatNumber(organisation.profiles_remaining, i18n.language),
              quota: formatNumber(organisation.profile_quota, i18n.language),
            }),
    );
    if (accessEnd) meta.push(t("workspace.accessUntil", { date: accessEnd }));
  }

  return (
    <>
      <div className="ph">
        <div>
          <h1>{t("workspace.title")}</h1>
          {meta.length > 0 ? <p className="meta">{meta.join(" · ")}</p> : null}
        </div>
        <div className="ph-actions">
          <div>
            {refused ? (
              <>
                <button
                  type="button"
                  className="btn btn-primary"
                  aria-disabled="true"
                  aria-describedby={refusalId}
                >
                  {t("workspace.newProfile")}
                </button>
                <p className="reason" id={refusalId}>
                  {t(`workspace.refusalShort.${refusal}`)}
                </p>
              </>
            ) : (
              <Link className="btn btn-primary" to="/profiles/new">
                {t("workspace.newProfile")}
              </Link>
            )}
          </div>
        </div>
      </div>

      {refused ? (
        <MessageBanner kind="note">
          <p>
            <span className="pfx">{t("workspace.notePrefix")}</span>{" "}
            {t(`workspace.refusalLong.${refusal}`, { date: accessEnd ?? "" })}
          </p>
        </MessageBanner>
      ) : null}

      {runs.length === 0 ? (
        <section className="empty" aria-labelledby="empty-h">
          <h2 id="empty-h">{t("workspace.emptyTitle")}</h2>
          <p>{t("workspace.emptyIntro")}</p>
          <ol>
            <li>{t("workspace.emptyStep1")}</li>
            <li>{t("workspace.emptyStep2")}</li>
            <li>{t("workspace.emptyStep3")}</li>
          </ol>
          {refused ? null : (
            <Link className="btn btn-primary" to="/profiles/new">
              {t("workspace.startFirst")}
            </Link>
          )}
        </section>
      ) : (
        <>
          <h2 className="vh">{t("workspace.listHeading")}</h2>
          <div className="toolbar">
            <span aria-live="polite">{t("workspace.selected", { count: selected.length })}</span>
            <button
              type="button"
              className="btn btn-secondary"
              aria-disabled={canCompare ? undefined : "true"}
              aria-describedby={canCompare ? undefined : compareWhyId}
              onClick={compare}
            >
              {t("workspace.compare")}
            </button>
            {canCompare ? null : (
              <span className="meta" id={compareWhyId}>
                {t("workspace.compareWhy")}
              </span>
            )}
          </div>
          <table className="tbl">
            <caption className="vh">{t("workspace.caption")}</caption>
            <thead>
              <tr>
                <th scope="col" className="w-chk">
                  <span className="vh">{t("workspace.selectColumn")}</span>
                  {t("workspace.compareColumn")}
                </th>
                <th scope="col">{t("workspace.supplier")}</th>
                <th scope="col">{t("workspace.status")}</th>
                <th scope="col">{t("workspace.updated")}</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <RunRow
                  key={run.id}
                  run={run}
                  checked={selected.includes(run.id)}
                  open={run.id === openRun}
                  onToggle={() => toggle(run.id)}
                />
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}

function RunRow({
  run,
  checked,
  open,
  onToggle,
}: {
  run: Run;
  checked: boolean;
  open: boolean;
  onToggle: () => void;
}) {
  const { t, i18n } = useTranslation();
  const whyId = useId();
  const name = run.supplier_name ?? t("workspace.nameHidden");
  const comparable = HAS_PROFILE.includes(run.status);
  // A run still going, or one that ended without a profile, opens its progress page; a profile its card.
  const target = comparable ? `/profiles/${run.id}` : `/profiles/${run.id}/run`;
  return (
    <tr className={checked || open ? "sel" : undefined}>
      <td data-label={t("workspace.compareColumn")}>
        <label className="chk">
          <input
            type="checkbox"
            checked={checked}
            disabled={!comparable}
            aria-describedby={comparable ? undefined : whyId}
            onChange={onToggle}
          />
          <span className="vh">{t("workspace.selectFor", { name })}</span>
        </label>
        {comparable ? null : (
          <span className="vh" id={whyId}>
            {t("workspace.noProfileYet")}
          </span>
        )}
      </td>
      <td className="name" data-label={t("workspace.supplier")}>
        <Link to={target} data-run-id={run.id} aria-current={open ? "true" : undefined}>
          {name}
        </Link>
      </td>
      <td data-label={t("workspace.status")}>{t(`workspace.statuses.${run.status}`)}</td>
      <td data-label={t("workspace.updated")}>{formatDate(lastUpdated(run), i18n.language)}</td>
    </tr>
  );
}

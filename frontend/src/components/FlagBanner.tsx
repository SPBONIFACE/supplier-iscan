// Flag banner (design brief § 6 and 7): a state the buyer should notice, in ink on the margin paper with a
// left rule. Not an error and not a missing fact. Reused by the run screen and the supplier card (#34, #35).
import type { ReactNode } from "react";

type FlagBannerProps = {
  /** The micro-label that names the flag, e.g. "insufficient sources". Rendered as text. */
  label: string;
  children: ReactNode;
  /** `status` is announced politely; `none` is for a banner that is already part of the page content. */
  live?: "status" | "none";
};

export function FlagBanner({ label, children, live = "status" }: FlagBannerProps) {
  return (
    <div className="flag" role={live === "status" ? "status" : undefined}>
      <span className="ml">{label}</span>
      {children}
    </div>
  );
}

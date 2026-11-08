import { useEffect } from "react";

/** Sets the browser tab title (product name last), so each screen is announced on navigation. */
export function useTitle(title: string): void {
  useEffect(() => {
    document.title = `${title} · Supplier iScan`;
  }, [title]);
}

// Links that come from collected sources or from the API are opened only when they are http or https.
// Anything else (javascript:, data:, a relative path, text that is not an address) is shown as text.

/** The address as a normalised string when it is an http or https URL, else null. */
export function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

/** A website as the buyer gave it, with or without a scheme: https is assumed when there is none. */
export function websiteUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  const text = value.trim();
  if (/^[a-z][a-z0-9+.-]*:/i.test(text) && !/^[a-z0-9.-]+:\d+/i.test(text))
    return safeHttpUrl(text);
  return safeHttpUrl(`https://${text}`);
}

/** The host of an address, for display ("example.org"), or null. */
export function hostOf(value: string | null | undefined): string | null {
  const href = safeHttpUrl(value);
  return href ? new URL(href).hostname.replace(/^www\./, "") : null;
}

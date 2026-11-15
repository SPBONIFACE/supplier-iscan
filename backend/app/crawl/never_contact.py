"""Domains whose terms forbid automated collection are never contacted (#186).

One helper, shared by the collector (every address it is about to request) and the fetcher
(every redirect hop), so that no request, robots.txt and tdmrep.json included, reaches them.
"""


def host_matches(host: str, suffixes: tuple[str, ...]) -> bool:
    """`host` equals a suffix or ends with "." and the suffix (`notlinkedin.com` does not match)."""
    host = host.lower().rstrip(".")
    return any(host == s or host.endswith("." + s) for s in suffixes)

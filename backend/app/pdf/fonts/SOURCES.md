# Fonts: IBM Plex (self-hosted)

IBM Plex Sans, Serif, Mono and Sans JP, KR, SC, SIL Open Font License 1.1 (`OFL.txt`, copyright IBM Corp.,
Reserved Font Name "Plex"). The files are the web fonts **as distributed by IBM**, unmodified (no re-subsetting
by us).

- Source: the IBM/plex repository on GitHub (https://github.com/IBM/plex), commit
  `71f558992315a12ca1f06a2215d57962a1992162`
  - Latin, Cyrillic, Greek: `packages/plex-{sans,serif,mono}/fonts/split/woff2/`
  - JP, KR, SC: `packages/plex-sans-{jp,kr,sc}/fonts/split/woff2/unhinted/` (split by `unicode-range`)
  - Licence: `packages/plex-sans/LICENSE.txt` (identical in the six packages; sha256 prefix `7e6b2818edbd`)
- Weights: Sans 400/500/600, Serif 400/600, Mono 400, Sans JP/KR/SC 400/600.
- Checksums: `SHA256SUMS` (sha256 of every file as downloaded). Verify with `shasum -a 256 -c SHA256SUMS`.
- `src/styles/fonts.css` holds the `@font-face` rules (IBM's `unicode-range` values, URLs under `/fonts/`).
- U+202F (French narrow no-break space) is in the `Pi` subset of each family.
- No third-party CDN at run time.

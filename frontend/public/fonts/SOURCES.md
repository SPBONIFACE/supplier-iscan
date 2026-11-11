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

# Fonts: supplier card (self-hosted, #163)

Piazzolla (copyright 2018 The Piazzolla Project Authors) and Barlow Semi Condensed (copyright 2017 The Barlow
Project Authors), SIL Open Font License 1.1 (`card/OFL-piazzolla.txt`, `card/OFL-barlowsemicondensed.txt`).
Used by the supplier card page only (tearsheet redesign, mock-up `05-supplier-card-tearsheet.html`). Approved by
the owner on 11 Nov 2026 (owner decision 7 of the approved list in `_docs/process/`).

- Source: Google Fonts web fonts as served by `fonts.gstatic.com`, downloaded on 11 Nov 2026, unmodified;
  licences from the google/fonts repository (`ofl/piazzolla/OFL.txt`, `ofl/barlowsemicondensed/OFL.txt`).
- Subsets: Latin and Latin Extended (`unicode-range` as served by Google Fonts); Piazzolla 400, 600, italic 400;
  Barlow Semi Condensed 500, 700, 800.
- Checksums: in `SHA256SUMS`. `src/styles/card.css` holds the `@font-face` rules (URLs under `/fonts/card/`).
- No third-party CDN at run time.

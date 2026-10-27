# Supplier iScan: design brief

> **Status: proposed, pending the owner's approval on issue #3 or its pull request.** Until the owner approves it,
> no mock-up (#4 to #7) and no frontend or PDF work builds on this brief or on `tokens.json`.

This brief fixes the visual direction, the shared components, the status vocabulary and the design tokens of Supplier
iScan. Every mock-up, the frontend (#31 onwards) and the server-side PDF (#39, #40) build on it. The tokens live in one
machine-readable file, [`tokens.json`](tokens.json); the tables below reproduce it.

Sources: [`spec.md`](../product/spec.md) (§ F1, F3, F4, F5, F8, F9, Non-functional requirements), the domain terms of
[`pm.md`](../team/pm.md), and the design decisions the owner took on 27 Oct 2026, stated here as the agreed direction.

## 1. Direction: editorial dossier

A supplier profile reads like a research dossier from a quality business publication: a document the buyer reads,
checks and annotates, not a dashboard.

- **Serif headings** (IBM Plex Serif) for supplier names and section titles; the app's working text in IBM Plex Sans.
- **Thin horizontal rules instead of cards.** Sections are separated by a 2px ink rule above the title; rows by a
  hairline. No shadows, no gradients, no glass, no rounded pill cards.
- **Quotes are article blockquotes**: a left rule, the quote in Plex Serif, the source line underneath ("Found in
  \<source\> on \<date\>"). They are visually distinct from the app's own text.
- **Status as micro-labels**: small uppercase labels that always carry text. Colour never carries a status alone.
- **The evidence panel is the document's margin note**: the Quote, its source and link sit beside (or under) the fact,
  like a side note in the margin of a page.
- **The PDF looks like a research brief**, typeset with the same tokens, not a screenshot of the screen.

### Principles

1. **The AI proposes; the buyer decides.** Every AI output reads as a proposal until a member acts on it. Pending
   items look visibly unfinished (dashed label); decided items look settled (solid label) and name who decided.
2. **Two separate status channels.** *Evidence status* (source type, the quote and where it was found, missing
   evidence) belongs to the source line and the margin note. *Buyer review status* (`proposed`, `approved`,
   `corrected`; `ai_draft`, `approved`, `corrected`, `deleted`) belongs to the status column. They never share a
   shape, a position or a wording. **An approved fact never looks "independently verified"**: the label reads
   "Approved" and the byline names the member ("Approved by \<name\> on \<date\>"); the words "verified", "validated
   by the system" or "confirmed" are not used for review status, and no check-mark, seal or shield icon is used.
3. **Grounding is shown by the source line, not by a badge.** A displayed fact has always passed the *Grounding
   check* (ungrounded values are discarded, spec § F3), so the brief adds no grounding badge; the line "Found in
   \<source\> on \<date\>" and the Quote are the evidence.
4. **Brick red means missing evidence, and only that.** "No public evidence found" and *Evidence gaps* use brick. No
   other state, error or warning uses it, so the colour keeps one meaning.
5. **Missing is never negative.** Missing information reads "No public evidence found", never "does not have", and is
   never abbreviated to a dash or an empty cell.
6. **No generic AI-SaaS patterns.** No sparkle or magic icons on AI features; no confidence percentages (the
   `confidence` of an `IdentityProposal` is never displayed as a number); no traffic-light scores; no aggregate scores;
   no oversized KPI cards. A level (low / medium / high) appears only as a word next to its cited facts (spec § F8).
7. **Compact working tool.** Tight rows and tables, more facts per screen, layouts that line up across suppliers for
   comparison.
8. **Accessible by construction.** WCAG 2.1 AA: every pair in § 4 meets its ratio; keyboard operation of review and
   comparison; visible focus; text labels for every status; exact wording kept in the DOM.

## 2. Typography

### Families and roles

| Role | Family | Weights | Used for |
| :--- | :--- | :--- | :--- |
| Headings | IBM Plex Serif | 600 (headings), 400 (quotes) | Supplier name, section titles, field-group titles; quote blocks |
| UI and body | IBM Plex Sans | 400, 500, 600 | All app text, tables, forms, micro-labels (600), buttons (500) |
| Identifiers | IBM Plex Mono | 400 | LEI, registry numbers, Wikidata ids, domains and URLs where alignment helps |
| Non-Latin quotes and names | IBM Plex Sans JP, IBM Plex Sans KR, IBM Plex Sans SC | 400, 600 | Quotes, supplier names and values in Japanese, Korean, Chinese |

No italic is used: CJK fonts have no italic and synthetic italics hurt legibility. Emphasis is by weight or by a
micro-label. Numbers in tables and dates use tabular figures (`font-variant-numeric: tabular-nums`).

### Licence and hosting

- All families are under the **SIL Open Font License 1.1**, which allows bundling with software, serving as web fonts
  and embedding in PDF documents. The `OFL.txt` licence and copyright notice ship next to the font files.
- **Self-hosted**: the fonts are served by the application from its own origin (e.g. `/fonts/…`) for the web, and read
  from local files by WeasyPrint for the PDF. Never a third-party CDN at run time; the content security policy allows
  fonts from `'self'` only. The PDF renderer does not fetch any remote URL.
- Font files are **not committed by this issue**; #31 adds them (web) and #39 uses them (PDF).
- [Claude addition, to be confirmed by the owner. Source: SIL OFL 1.1 text and OFL-FAQ, scripts.sil.org/OFL.]
  IBM Plex carries the Reserved Font Name "Plex". Prefer the web-font files and subsets **as distributed by IBM** over
  re-subsetting them ourselves, since a modified font may not keep the reserved name. Subsetting done by WeasyPrint
  when it embeds a font in a PDF is document embedding.

### Files and subsets needed

| Family | Weights | Character coverage needed | Web format | PDF format |
| :--- | :--- | :--- | :--- | :--- |
| IBM Plex Serif | 400, 600 | Latin incl. Latin-1 and Latin Extended-A (French: é è ê ë à â ç î ï ô û ù ü ÿ œ æ and capitals É È Ê À Ç Œ), punctuation « » ‹ › ’ “ ” – — … and U+00A0, U+202F (French spacing), € | WOFF2 | TTF/OTF of the same release |
| IBM Plex Sans | 400, 500, 600 | Same as Serif, plus Cyrillic and Greek where the family provides them (quotes stay in their source language) | WOFF2 | TTF/OTF |
| IBM Plex Mono | 400 | Basic Latin, Latin-1 | WOFF2 | TTF/OTF |
| IBM Plex Sans JP / KR / SC | 400, 600 | Full CJK, loaded through `unicode-range` so a browser downloads a chunk only when the page contains it | WOFF2, split by `unicode-range` | TTF/OTF (WeasyPrint embeds only the glyphs used) |

The CJK families are large (several megabytes each); split loading keeps them off pages that do not need them. If
the IBM distribution of the pinned release does not provide split web files, #31 raises it (splitting needs a tool,
which is a dependency to approve). #31 checks that U+202F is in the Latin files; if it is missing, French spacing falls
back to U+00A0.

### Fallback stacks (from `tokens.json`)

- **Serif**: `"IBM Plex Serif", Georgia, "Times New Roman", "IBM Plex Sans JP", "IBM Plex Sans KR", "IBM Plex Sans SC",
  "Hiragino Mincho ProN", "Noto Serif CJK JP", "Songti SC", serif`
- **Sans**: `"IBM Plex Sans", "IBM Plex Sans JP", "IBM Plex Sans KR", "IBM Plex Sans SC", system-ui, -apple-system,
  "Segoe UI", "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Apple SD Gothic Neo", "PingFang SC", "Microsoft YaHei",
  "Malgun Gothic", "Yu Gothic", "Noto Sans CJK JP", "Noto Sans", Arial, sans-serif`
- **Mono**: `"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace`

How the stacks render each script:

- **French accents**: covered by Plex Serif and Plex Sans themselves; uppercase micro-labels keep their accents
  ("IDENTITÉ À VÉRIFIER") because the uppercase is applied by CSS on a correctly tagged `lang="fr"` element.
- **CJK**: Plex Serif and Plex Sans have no CJK glyphs, so the browser falls through, character by character, to Plex
  Sans JP / KR / SC, then to the system CJK fonts. CJK headings therefore render in Plex Sans CJK (there is no Plex
  Serif CJK); this is intended.
- **Han characters are shared** by Japanese and Chinese but drawn differently. When the language of a quote or a name
  is known, the element carries `lang` (`ja`, `ko`, `zh-Hans`, `zh-Hant`) and a `:lang()` rule moves the matching Plex
  family to the front of the stack. When it is unknown, the default order above (JP, KR, SC) applies.
- **Other scripts** (Arabic, Hebrew, Thai, Devanagari, …): system fonts through `system-ui`, `Noto Sans` and the
  generic family. Quote blocks carry `dir="auto"` so right-to-left quotes run correctly.

Rendering test strings for #31 and #39 (web and PDF): `Société Générale – « Identité à vérifier » ; Œuvre, ÉÈÀÇ`,
`株式会社日立製作所`, `삼성전자 주식회사`, `华为技术有限公司`, `ООО «Северсталь»`, and a quote with `[…]`.

### Type scale (compact)

| Token | Size | Family, weight | Line height | Use |
| :--- | :--- | :--- | :--- | :--- |
| `font.size.micro` | 11px | Sans 600, uppercase, letter-spacing 0.06em | 1.2 | Micro-labels |
| `font.size.sm` | 12px | Sans 400 / 600 | 1.35 | Metadata, source lines, table headers, field labels |
| `font.size.base` | 14px | Sans 400 | 1.35 (cells), 1.5 (prose) | UI and body text, table cells |
| `font.size.quote` | 15px | Serif 400 | 1.5 | Quote blocks |
| `font.size.h3` | 16px | Serif 600 | 1.2 | Field-group titles |
| `font.size.h2` | 19px | Serif 600 | 1.2 | Section titles |
| `font.size.h1` | 24px | Serif 600 | 1.2 | Supplier name (large text in WCAG terms) |
| `font.size.display` | 30px | Serif 600 | 1.2 | PDF cover title only |

Sizes are in CSS px for both media. In the PDF, 1px = 0.75pt, so body text prints at 10.5pt and micro-labels at
8.25pt.

## 3. Colour

Dark ink on paper white. **Cobalt** for actions, links, navigation and focus. **Brick red** reserved for missing
evidence. Every other status uses ink and neutral greys with a text label.

| Token | Value | Role |
| :--- | :--- | :--- |
| `color.paper` | `#FCFBF8` | Page background (paper white) |
| `color.paper-margin` | `#F3F1EB` | Evidence margin note, side panel, flag banner background |
| `color.field` | `#FFFFFF` | Form field background; PDF page background |
| `color.cobalt-tint` | `#EAEFFB` | Selected or hovered row (table, comparison) |
| `color.skeleton` | `#E6E3DC` | Static loading placeholders (decorative) |
| `color.ink` | `#1B1B1A` | Primary text, headings, strong rules, decided status labels |
| `color.ink-secondary` | `#45443F` | Secondary text, micro-labels, quote source lines |
| `color.ink-tertiary` | `#5F5D56` | Metadata, pending-status borders, quote rule |
| `color.ink-disabled` | `#6B6961` | Text of disabled controls |
| `color.cobalt` | `#1F4BC4` | Actions, links, navigation, focus indicator |
| `color.cobalt-strong` | `#173A99` | Hover and pressed actions, visited links |
| `color.on-cobalt` | `#FFFFFF` | Text on cobalt fills (primary button) |
| `color.brick` | `#A3361F` | **Reserved**: "No public evidence found" and evidence gaps |
| `color.border-control` | `#7D7A71` | Boundary of form fields and secondary buttons |
| `color.rule` | `#D9D6CE` | Hairline separators (decorative) |

**Dark theme:** not defined. It is not free: every pair in § 4 would need a second set of values and checks, and the
paper metaphor and the PDF are light by nature. The tokens are semantic (components use `status.*` and role names,
not raw values), so a dark theme can be added later as a second value set without touching components.

## 4. Contrast

Ratios computed with the WCAG 2.1 relative-luminance formula from the values in `tokens.json`. Thresholds: 4.5:1 for
body text (all text in this system is checked at 4.5:1, including large text, which only needs 3:1); 3:1 for UI
components, graphical objects and focus indicators. Decorative hairlines and loading blocks carry no information and
are not component boundaries; their ratios are shown for completeness. The PDF page is `color.field` (white); its
ratios are the `field` rows and, for every foreground, are at least as high as on `paper`.

| Foreground | Background | Kind | Use | Ratio | Result |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ink` `#1B1B1A` | `paper` `#FCFBF8` | Text | Body text, headings, values, decided status labels | **16.66:1** | AA pass (≥ 4.5:1) |
| `ink` `#1B1B1A` | `paper-margin` `#F3F1EB` | Text | Text in the evidence margin note, side panel, flag banner | **15.26:1** | AA pass (≥ 4.5:1) |
| `ink` `#1B1B1A` | `field` `#FFFFFF` | Text | Text typed in a form field; PDF body text | **17.24:1** | AA pass (≥ 4.5:1) |
| `ink` `#1B1B1A` | `cobalt-tint` `#EAEFFB` | Text | Text in a selected or hovered row | **14.97:1** | AA pass (≥ 4.5:1) |
| `ink-secondary` `#45443F` | `paper` `#FCFBF8` | Text | Secondary text; micro-labels (pending, source type, AI draft); quote source line | **9.43:1** | AA pass (≥ 4.5:1) |
| `ink-secondary` `#45443F` | `paper-margin` `#F3F1EB` | Text | Same, in the margin note and side panel | **8.64:1** | AA pass (≥ 4.5:1) |
| `ink-secondary` `#45443F` | `field` `#FFFFFF` | Text | Help text under a field | **9.76:1** | AA pass (≥ 4.5:1) |
| `ink-secondary` `#45443F` | `cobalt-tint` `#EAEFFB` | Text | Micro-labels in a selected row | **8.48:1** | AA pass (≥ 4.5:1) |
| `ink-tertiary` `#5F5D56` | `paper` `#FCFBF8` | Text | Metadata (dates, counts), deleted statement text | **6.37:1** | AA pass (≥ 4.5:1) |
| `ink-tertiary` `#5F5D56` | `paper-margin` `#F3F1EB` | Text | Metadata in the margin note | **5.83:1** | AA pass (≥ 4.5:1) |
| `ink-tertiary` `#5F5D56` | `field` `#FFFFFF` | Text | Placeholder text in a field | **6.59:1** | AA pass (≥ 4.5:1) |
| `ink-tertiary` `#5F5D56` | `cobalt-tint` `#EAEFFB` | Text | Metadata in a selected row | **5.72:1** | AA pass (≥ 4.5:1) |
| `ink-disabled` `#6B6961` | `paper` `#FCFBF8` | Text | Disabled control label (WCAG exempts it; kept at AA anyway) | **5.31:1** | AA pass (≥ 4.5:1) |
| `ink-disabled` `#6B6961` | `paper-margin` `#F3F1EB` | Text | Disabled control in the side panel | **4.87:1** | AA pass (≥ 4.5:1) |
| `ink-disabled` `#6B6961` | `field` `#FFFFFF` | Text | Disabled field value | **5.50:1** | AA pass (≥ 4.5:1) |
| `ink-disabled` `#6B6961` | `cobalt-tint` `#EAEFFB` | Text | Disabled control in a selected row | **4.78:1** | AA pass (≥ 4.5:1) |
| `cobalt` `#1F4BC4` | `paper` `#FCFBF8` | Text | Links, text buttons, source chips, navigation | **7.09:1** | AA pass (≥ 4.5:1) |
| `cobalt` `#1F4BC4` | `paper-margin` `#F3F1EB` | Text | Links in the margin note (source URL, "Verify on IAF CertSearch") | **6.50:1** | AA pass (≥ 4.5:1) |
| `cobalt` `#1F4BC4` | `field` `#FFFFFF` | Text | Link inside a field area; PDF links | **7.34:1** | AA pass (≥ 4.5:1) |
| `cobalt` `#1F4BC4` | `cobalt-tint` `#EAEFFB` | Text | Link in a selected row | **6.37:1** | AA pass (≥ 4.5:1) |
| `cobalt-strong` `#173A99` | `paper` `#FCFBF8` | Text | Hovered or visited link | **9.66:1** | AA pass (≥ 4.5:1) |
| `cobalt-strong` `#173A99` | `paper-margin` `#F3F1EB` | Text | Hovered or visited link in the margin note | **8.85:1** | AA pass (≥ 4.5:1) |
| `cobalt-strong` `#173A99` | `cobalt-tint` `#EAEFFB` | Text | Hovered link in a selected row | **8.68:1** | AA pass (≥ 4.5:1) |
| `on-cobalt` `#FFFFFF` | `cobalt` `#1F4BC4` | Text | Primary button label | **7.34:1** | AA pass (≥ 4.5:1) |
| `on-cobalt` `#FFFFFF` | `cobalt-strong` `#173A99` | Text | Primary button label, hover and pressed | **9.99:1** | AA pass (≥ 4.5:1) |
| `brick` `#A3361F` | `paper` `#FCFBF8` | Text | "No public evidence found", evidence gap text | **6.54:1** | AA pass (≥ 4.5:1) |
| `brick` `#A3361F` | `paper-margin` `#F3F1EB` | Text | Missing evidence in the margin note | **5.99:1** | AA pass (≥ 4.5:1) |
| `brick` `#A3361F` | `cobalt-tint` `#EAEFFB` | Text | Missing evidence in a selected comparison row | **5.87:1** | AA pass (≥ 4.5:1) |
| `brick` `#A3361F` | `field` `#FFFFFF` | Text | Missing evidence in the PDF | **6.76:1** | AA pass (≥ 4.5:1) |
| `cobalt` `#1F4BC4` | `paper` `#FCFBF8` | UI / focus | Focus indicator (2px, 2px offset); primary button fill boundary | **7.09:1** | AA pass (≥ 3:1) |
| `cobalt` `#1F4BC4` | `paper-margin` `#F3F1EB` | UI / focus | Focus indicator in the margin note and side panel | **6.50:1** | AA pass (≥ 3:1) |
| `cobalt` `#1F4BC4` | `field` `#FFFFFF` | UI / focus | Focus indicator on a field | **7.34:1** | AA pass (≥ 3:1) |
| `cobalt` `#1F4BC4` | `cobalt-tint` `#EAEFFB` | UI / focus | Focus indicator and selection bar in a selected row | **6.37:1** | AA pass (≥ 3:1) |
| `border-control` `#7D7A71` | `paper` `#FCFBF8` | UI / focus | Field and secondary-button boundary | **4.15:1** | AA pass (≥ 3:1) |
| `border-control` `#7D7A71` | `paper-margin` `#F3F1EB` | UI / focus | Field boundary in the side panel | **3.80:1** | AA pass (≥ 3:1) |
| `border-control` `#7D7A71` | `field` `#FFFFFF` | UI / focus | Field boundary seen from inside the field | **4.29:1** | AA pass (≥ 3:1) |
| `border-control` `#7D7A71` | `cobalt-tint` `#EAEFFB` | UI / focus | Checkbox boundary in a selected row | **3.73:1** | AA pass (≥ 3:1) |
| `ink` `#1B1B1A` | `paper` `#FCFBF8` | UI / focus | Decided status border; error border (2px); flag rule (4px); section rule | **16.66:1** | AA pass (≥ 3:1) |
| `ink` `#1B1B1A` | `paper-margin` `#F3F1EB` | UI / focus | Flag banner rule against its own background | **15.26:1** | AA pass (≥ 3:1) |
| `ink-tertiary` `#5F5D56` | `paper` `#FCFBF8` | UI / focus | Pending status dashed border; quote left rule | **6.37:1** | AA pass (≥ 3:1) |
| `ink-tertiary` `#5F5D56` | `paper-margin` `#F3F1EB` | UI / focus | Quote left rule in the margin note | **5.83:1** | AA pass (≥ 3:1) |
| `ink-tertiary` `#5F5D56` | `cobalt-tint` `#EAEFFB` | UI / focus | Pending status border in a selected row | **5.72:1** | AA pass (≥ 3:1) |
| `brick` `#A3361F` | `paper` `#FCFBF8` | UI / focus | Missing-evidence left rule | **6.54:1** | AA pass (≥ 3:1) |
| `brick` `#A3361F` | `paper-margin` `#F3F1EB` | UI / focus | Missing-evidence left rule in the margin note | **5.99:1** | AA pass (≥ 3:1) |
| `rule` `#D9D6CE` | `paper` `#FCFBF8` | Decorative | Hairline row and section separators | 1.40:1 | n/a (decorative) |
| `rule` `#D9D6CE` | `paper-margin` `#F3F1EB` | Decorative | Hairlines in the margin note | 1.29:1 | n/a (decorative) |
| `skeleton` `#E6E3DC` | `paper` `#FCFBF8` | Decorative | Loading placeholder block (loading is also announced in text) | 1.24:1 | n/a (decorative) |

**Result: 44 of 44 informative pairs meet WCAG 2.1 AA; none fails.** Status colours by channel: missing evidence
(brick) 5.87 to 6.76:1; pending (ink-secondary text 8.48 to 9.76:1, ink-tertiary dashed border 5.72 to 6.37:1);
decided (ink 14.97 to 17.24:1); flags (ink on paper-margin 15.26:1); focus (cobalt 6.37 to 7.34:1).

**No status is conveyed by colour alone.** Every status in § 6 has a text label in the DOM. Shape adds a second
channel: dashed border = awaiting the buyer; solid border = decided by the buyer; borderless label in the source line =
evidence; thick left rule = profile flag; brick text plus a brick left rule plus the words "No public evidence found" =
missing evidence. The selected row adds a 3px cobalt bar and a checked checkbox to its tint.

## 5. Token table

The full token set of [`tokens.json`](tokens.json) (format: W3C Design Tokens Community Group draft, `$value` /
`$type`; aliases written `{group.token}`). Colour tokens are listed in § 3.

### Status aliases

| Token | Value | Applies to |
| :--- | :--- | :--- |
| `status.missing.fg`, `status.missing.rule` | `{color.brick}` | "No public evidence found", evidence gaps |
| `status.pending.fg` | `{color.ink-secondary}` | Fact `proposed`; statement `ai_draft` |
| `status.pending.border` / `.border-style` | `{color.ink-tertiary}` / `dashed` | Same |
| `status.decided.fg`, `status.decided.border` / `.border-style` | `{color.ink}` / `solid` | `approved`, `corrected` (facts and statements) |
| `status.deleted.fg`, `status.deleted.border` / `.border-style` | `{color.ink-tertiary}` / `solid` | Statement `deleted` (history only) |
| `status.evidence.fg` | `{color.ink-secondary}` | "Supplier's own claim", "Third-party source", "Redacted extract" |
| `status.flag.fg`, `status.flag.rule` | `{color.ink}` | "identity to verify", "partial", "insufficient sources", "source excluded at the site owner's request" |
| `status.flag.bg` | `{color.paper-margin}` | Flag banner background |
| `status.not-assessed.fg` | `{color.ink-secondary}` | "Not assessed: natural-person business" |
| `status.error.fg`, `status.error.border` | `{color.ink}` | Form and system errors (see § 10, decision 1) |
| `focus.color` / `focus.width` / `focus.offset` | `{color.cobalt}` / `2px` / `2px` | Focus indicator on every interactive element |

### Typography

| Token | Value |
| :--- | :--- |
| `font.family.serif` | see § 2, Fallback stacks |
| `font.family.sans` | see § 2, Fallback stacks |
| `font.family.mono` | see § 2, Fallback stacks |
| `font.weight.regular` / `.medium` / `.semibold` | 400 / 500 / 600 |
| `font.size.micro` / `.sm` / `.base` / `.quote` / `.h3` / `.h2` / `.h1` / `.display` | 11 / 12 / 14 / 15 / 16 / 19 / 24 / 30 px |
| `font.line-height.tight` / `.compact` / `.body` | 1.2 / 1.35 / 1.5 |
| `font.letter-spacing.micro` | 0.06em |

### Spacing, sizes, borders, radius

| Token | Value | Use |
| :--- | :--- | :--- |
| `space.0` … `space.8` | 0, 2, 4, 8, 12, 16, 24, 32, 48 px | 4px-based scale; cell padding `space.2` `space.3`, between sections `space.6` |
| `size.row` | 32px | Minimum height of a table row or fact row |
| `size.control` | 32px | Buttons and single-line fields |
| `size.target-min` | 24px | Minimum pointer target |
| `size.panel` | 560px | Supplier card side panel at desktop |
| `size.margin-note` | 300px | Evidence margin-note column |
| `size.label-column` | 200px | Field-label column in fact rows and the comparison |
| `size.measure` | 72ch | Maximum prose line length |
| `border.hairline` / `.control` | 1px | Row separators; field and button boundaries |
| `border.error` | 2px | Field in error |
| `border.quote-rule` | 2px | Quote left rule (`color.ink-tertiary`); missing-evidence rule (`color.brick`) |
| `border.section-rule` | 2px | Ink rule above a section title |
| `border.flag-rule` | 4px | Flag banner left rule |
| `border.selection` | 3px | Cobalt bar on the left of a selected row |
| `radius.none` | 0px | Default: rules, panels, tables, quotes, banners |
| `radius.control` | 2px | Buttons, fields, micro-labels, source chips. No pill shapes |

## 6. Status vocabulary

English wording is exact from the spec. Where the spec gives only a status code (`proposed`, `ai_draft`, …), the
display label is the code written as a word; the code itself never appears in the UI. The DOM string is the wording
below in sentence case; micro-labels are uppercased by CSS only, so screen readers and copy-paste get the exact
wording. **French column: to be confirmed by the owner.** French labels follow the tone of the AI disclosure in spec
§ F1 (vouvoiement, plain professional wording) and French spacing before ":".

| Label | Meaning | English (spec) | French (to be confirmed by the owner) | Visual treatment |
| :--- | :--- | :--- | :--- | :--- |
| Fact `proposed` | Extracted by the AI with a grounded Quote; no member has reviewed it | "Proposed" (`proposed`) | « Proposé » | Review channel. Micro-label, `status.pending`: ink-secondary text, 1px dashed ink-tertiary border, radius 2px. The card header counts them: "\<n\> facts still proposed" (wording not fixed by the spec) |
| Fact `approved` | A member accepted the value as proposed. Says nothing about independent verification | "Approved" (`approved`); byline "Approved by \<name\> on \<date\>" | « Approuvé » ; « Approuvé par \<nom\> le \<date\> » | Review channel. Micro-label, `status.decided`: ink text, 1px solid ink border. Byline in ink-tertiary. No check-mark or seal |
| Fact `corrected` | A member replaced the AI value; the original AI value and Quote are kept alongside (F4) | "Corrected" (`corrected`); "Original AI value" | « Corrigé » ; « Valeur d'origine proposée par l'IA » | Review channel. Micro-label, `status.decided`. Corrected value in ink; under it "Original AI value: …" in ink-tertiary, with its source chip kept |
| Source type `supplier_claim` | The source is on the supplier's own website or registry identity | "Supplier's own claim" | « Déclaration du fournisseur » | Evidence channel. Borderless micro-label, `status.evidence` (ink-secondary), placed in the quote's source line, never in the status column |
| Source type `third_party` | The source is outside the supplier's domain and identifiers | "Third-party source" | « Source tierce » | Evidence channel. Same as above |
| Statement `ai_draft` | Assessment statement drafted by the AI, not yet acted on by a member | "AI draft, pending your validation" (PDF: "AI draft") | « Brouillon IA, en attente de votre validation » (PDF : « Brouillon IA ») | AI-draft label (§ 7.6): `status.pending`, dashed. Provenance on demand |
| Statement `approved` | A member approved the statement | "Approved"; byline "Reviewed by \<name\> on \<date\>" (PDF: "reviewed by …", F9) | « Approuvé » ; « Revu par \<nom\> le \<date\> » | Review channel. Micro-label, `status.decided`, solid |
| Statement `corrected` | A member edited the statement; the AI text is kept in its provenance | "Corrected"; byline "Reviewed by \<name\> on \<date\>" | « Corrigé » ; « Revu par \<nom\> le \<date\> » | Review channel. Micro-label, `status.decided`, solid |
| Statement `deleted` | A member deleted the statement; kept only in its history | "Deleted" | « Supprimé » | Not shown in the assessment. In history or provenance: micro-label `status.deleted` (ink-tertiary, solid border), text struck through in ink-tertiary |
| Missing evidence (`not_found`) | No grounded Quote was found for the field. Not a statement about the supplier | "No public evidence found" | « Aucune information publique trouvée » | Evidence channel. Brick text (`status.missing.fg`) with a 2px brick left rule; no source chip, no review label. Never shortened or replaced by a dash |
| Evidence gap | An assessment statement naming the missing evidence and what would close it (F8) | "Evidence gap" (domain term) followed by the named evidence | « Information manquante » | Brick micro-label and 2px brick left rule; the gap text in ink. Financial gaps use the guidance text, never LLM text |
| "Redacted extract" | The Quote contains redactions, each marked `[…]` | "Redacted extract" | « Extrait caviardé » | Evidence channel. Borderless micro-label in the source line. `[…]` kept in ink inside the quote, with visually hidden text "redacted" / « caviardé » for screen readers |
| "identity to verify" | The confirmed company name was not found in its website's collected content (F1) | "identity to verify" | « identité à vérifier » | Flag banner (§ 7.5) under the card header: 4px ink left rule, paper-margin background, micro-label plus one sentence |
| "partial" | The run stopped on its cost budget; some sections are not covered (F7) | "partial", with the sections not covered | « partiel », avec « Sections non couvertes : … » | Flag banner; lists the sections not covered. In the workspace list: micro-label, `status.flag` |
| "source excluded at the site owner's request" | A domain was not crawled because of a TDM reservation, an AI-crawler block or the suppression list (F2) | "source excluded at the site owner's request" | « source exclue à la demande de l'éditeur du site » | Flag banner variant in the run log and card; ink, not brick (it is a respected exclusion, not missing evidence) |
| "insufficient sources" | Every collection strategy failed; the run ended without a profile and does not count against the quota (F2) | "insufficient sources" | « sources insuffisantes » | Flag banner with the failure log beneath; ink (see § 10, decision 2) |
| "Not assessed: natural-person business" | The identity is flagged `natural_person`; credit, financial-stability and risk statements are not drafted (F8, excluded uses) | "Not assessed: natural-person business" | « Non évalué : entreprise individuelle (personne physique) » | Section body text in ink-secondary under the section title; no AI-draft label, no brick |
| Source line | Where and when the Quote was found (F3) | "Found in \<source\> on \<date\>" | « Trouvé dans \<source\> le \<date\> » | Plex Sans 12px, ink-secondary, under every quote block |
| Certification link | Points to the certification register; the app never says a supplier is not certified (F3) | "Verify on IAF CertSearch" | « Vérifier sur IAF CertSearch » | Cobalt text link in the margin note of certification facts |
| Empty fit section | No buyer criteria entered (F8) | "Enter your criteria to assess fit" | « Saisissez vos critères pour évaluer l'adéquation » | Body text in ink-secondary with a cobalt link to the criteria field |
| AI disclosure | First chat interaction (F1) | Fixed text in spec § F1 | Fixed text in spec § F1 | Quoted verbatim from the spec, never reworded; plain body text in ink at the top of the chat, not a micro-label |
| PDF disclaimer | Regulatory text | Placeholder: comes from the owner's reviewed sources | Placeholder: comes from the owner's reviewed sources | Not drafted here (#39, #40) |

## 7. Shared components

Every component lists the six states. **Default** is the resting look; **focus** is keyboard focus (always the cobalt
2px outline with 2px offset unless stated); **disabled** covers read-only and demo modes (Flow 3: actions that would
call an LLM are disabled *with an explanation*); **loading**, **empty** and **error** as named. Hover is a refinement of
default (cobalt-strong for links and buttons, cobalt-tint for rows). No animation is required; any transition is
removed under `prefers-reduced-motion`.

### 7.1 Status badge (micro-label)

Displays one status from § 6 as text. Display only; the review action is a separate control (button or menu) next to
it.

| State | Treatment |
| :--- | :--- |
| Default | Inline box, Plex Sans 11px 600 uppercase, letter-spacing 0.06em, padding 1px 4px, radius 2px. Pending: ink-secondary text, 1px dashed ink-tertiary border. Decided: ink text, 1px solid ink border. Evidence: no border, ink-secondary. Byline beside it in 12px ink-tertiary when the status has one |
| Focus | Not focusable itself. When a badge is the visible face of the review menu button, that button takes the focus outline around the badge |
| Disabled | In read-only or demo views the badge shows unchanged (the status is still true); only the review control next to it is disabled |
| Loading | While a status change saves: the previous label stays, followed by "Saving…" / « Enregistrement… » in ink-tertiary; the row is `aria-busy="true"` |
| Empty | No status exists (field `not_found`, or a buyer field): no badge is drawn and no placeholder dash; the row shows its missing-evidence or buyer-input content instead |
| Error | The change was not saved: the previous label is restored and an inline message follows: "Error: status not saved. Retry" with a cobalt Retry link; announced with `role="alert"` |

### 7.2 Fact row

One profile field: label, value, source chip, review status and review action.

| State | Treatment |
| :--- | :--- |
| Default | Grid: label column 200px (Plex Sans 12px 600, ink-secondary) · value (14px ink; identifiers in Plex Mono) · source chip · status badge and review control (right-aligned, fixed width). Min height 32px, padding 4px 8px, hairline below. Corrected rows add the "Original AI value" line |
| Focus | Rows are reachable with Tab (one stop per row, roving tabindex) and Up/Down arrows; Tab inside a row moves to the chip, then the review control. Focused row: 2px cobalt outline inset; hovered row: cobalt-tint background |
| Disabled | Read-only or demo: review control disabled (ink-disabled text, dashed border-control boundary) with the reason as visible text on focus and hover and as `aria-describedby`, e.g. "Demo profiles are read-only". Value, chip and status stay fully readable |
| Loading | Label shown; value area replaced by a static skeleton bar (`color.skeleton`) of one line; the section has `aria-busy="true"` and a visually hidden "Loading…" |
| Empty | Field `not_found`: value reads "No public evidence found" in brick with a 2px brick left rule; no chip, no review label. Certification fields keep "Verify on IAF CertSearch" |
| Error | The row could not be loaded or saved: value area shows "Error: this field could not be loaded. Retry" in ink with a 2px ink left rule (never brick, so a failure is never read as missing evidence) |

### 7.3 Source chip

A compact button that reveals the **Quote** and the link of a fact in the evidence margin note.

| State | Treatment |
| :--- | :--- |
| Default | Rectangular box, radius 2px, 1px border-control boundary, Plex Sans 12px cobalt text: source publisher or domain and date (e.g. `example.com · 12 Oct 2026`, date per locale). A `button` with `aria-expanded` and `aria-controls` pointing at the margin note |
| Focus | Cobalt 2px outline, 2px offset. Enter or Space toggles the note; Escape closes it and returns focus to the chip |
| Disabled | Evidence stays reachable in every mode, demo and read-only included, so the chip is never disabled in normal use. If a parent must make it inert (for example while its row is saving), it shows ink-disabled text and a dashed border-control boundary and keeps its label |
| Loading | Opened while the Quote is being fetched: chip shows `aria-expanded="true"`, the margin note shows a static skeleton quote (left rule plus two bars) and "Loading source…" |
| Empty | The field has no source (`not_found`): no chip is rendered. In the PDF, the chip becomes a static source line (no button) |
| Error | The Quote could not be loaded: the margin note shows "Error: the source could not be loaded. Retry"; the chip keeps its label and stays operable |

Expanded (pressed) is shown by a cobalt-tint background and `aria-expanded="true"`, not by colour alone: the margin
note itself is the visible result.

### 7.4 Quote block

A verbatim passage from a source, visually distinct from the app's own text.

| State | Treatment |
| :--- | :--- |
| Default | `blockquote` with `lang` (when known) and `dir="auto"`. Plex Serif 15px, line height 1.5, ink, 2px ink-tertiary left rule, padding-left 12px, max 72ch. No quotation-mark ornaments, no background. Under it the source line: "Found in \<source\> on \<date\>" (12px ink-secondary), the source-type micro-label, "Redacted extract" when applicable, and the source URL as a cobalt link (Plex Mono when shown in full) |
| Focus | The block is not focusable; its link takes the cobalt outline. When the margin note opens, focus moves to the note's heading |
| Disabled | Not interactive; never greyed out, even in demo or read-only views, because evidence must stay legible |
| Loading | Left rule plus two static skeleton bars; "Loading source…" visually hidden |
| Empty | A fact without a Quote cannot exist (F3). If none is returned, the block is replaced by "No public evidence found" in brick, and the case is logged as a defect |
| Error | "Error: the source could not be loaded. Retry" in ink, inside the rule; the source line is kept when known |

### 7.5 Flag banner

Profile-level flags: "identity to verify", "partial", "insufficient sources", "source excluded at the site owner's
request".

| State | Treatment |
| :--- | :--- |
| Default | Full width under the card header: `status.flag.bg` (paper-margin), 4px ink left rule, padding 8px 12px. Micro-label (e.g. IDENTITY TO VERIFY) then one sentence in 14px ink explaining what to check, then an optional cobalt action link. Several flags stack, one per line. `role="status"` when it appears during a run |
| Focus | The banner is not focusable; its action link takes the cobalt outline |
| Disabled | In demo or read-only views the action link is disabled with its reason; the flag text stays |
| Loading | Not shown while the run stage that sets the flag is still running; the run progress shows the stage instead |
| Empty | No flag: nothing is rendered. There is no "all clear" banner, so the absence of a flag is never presented as a verification |
| Error | Flags could not be loaded: a message banner says "Error: the profile flags could not be loaded" so the absence of a flag is not mistaken for no flag |

### 7.6 AI-draft label

Marks an AI-drafted assessment statement and gives its provenance on demand.

| State | Treatment |
| :--- | :--- |
| Default | Micro-label "AI draft, pending your validation", `status.pending` (ink-secondary, 1px dashed ink-tertiary), followed by a cobalt "Details" disclosure that shows provider, model ID and version, generation time and review status (F8). No sparkle, robot or magic icon, no colour fill. After review it is replaced by the decided label and "Reviewed by \<name\> on \<date\>" |
| Focus | The "Details" disclosure takes the cobalt outline; Enter or Space toggles provenance |
| Disabled | In demo the label and provenance stay visible; the approve / correct / delete actions next to it are disabled with "Demo profiles are read-only" |
| Loading | Statement still being drafted: label reads "AI draft" with "Drafting…" in ink-tertiary and the section `aria-busy="true"` |
| Empty | No statement in a section: the label is not shown; the section shows its empty text (e.g. "Enter your criteria to assess fit", or "Not assessed: natural-person business") |
| Error | Provenance could not be loaded: "Error: details not available. Retry" inside the disclosure; the AI-draft label itself always stays |

### 7.7 Form field

Text input, textarea, select and checkbox (identity hints, criteria, buyer inputs, login, invitation).

| State | Treatment |
| :--- | :--- |
| Default | Label above (Plex Sans 12px 600, ink), field 32px high, white (`color.field`), 1px border-control boundary, radius 2px, 14px ink text, padding 4px 8px. Help text under it in 12px ink-secondary. Placeholder in ink-tertiary, never the only label |
| Focus | Cobalt 2px outline with 2px offset outside the field boundary |
| Disabled | Paper-margin background, dashed border-control boundary, ink-disabled text, `disabled` attribute; the reason in help text (e.g. "Not available in the demo") |
| Loading | While a value is checked (e.g. "None of these, enter the website" checks that the domain responds): "Checking…" / « Vérification… » after the field in ink-tertiary, `aria-busy="true"`; the field stays editable |
| Empty | Empty value: placeholder shown. A required empty field is flagged only after submit or blur, never on first view |
| Error | 2px ink boundary, `aria-invalid="true"`, message under the field starting with "Error:" / « Erreur : » in ink and linked by `aria-describedby`; focus moves to the first invalid field on submit |

### 7.8 Components also needed by #31

| Component | Default | Focus | Disabled | Loading | Empty | Error |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Button | Primary: cobalt fill, on-cobalt text, 500 weight, 32px, radius 2px. Secondary: 1px border-control boundary, ink text. Text button: cobalt text, underline on hover. Hover and pressed: cobalt-strong | Cobalt 2px outline, 2px offset | Primary and secondary: paper-margin fill, dashed border-control boundary, ink-disabled text, reason as visible text or `aria-describedby` | Label replaced by "Working…" style text (e.g. "Signing in…"); button `aria-disabled`, width kept | n/a: a button always has a label | The action's error appears in a message banner or under the related field, not on the button |
| Message banner | System messages after an action (saved, dependency down, quota reached). Full width, 2px ink left rule, no fill, prefix "Note:" / "Error:"; success reads "Saved." in ink, not green | Not focusable; its links take the outline | Not used | Not used: loading uses the loading indicator | Nothing rendered | `role="alert"`, prefix "Error:", plain language naming the dependency that failed (spec § Robustness cases) |
| Loading indicator | Text first: "Loading…" plus static skeleton bars. Run progress is a stage list (identity → collection → extraction → assessment) with micro-labels DONE / IN PROGRESS / WAITING and the remaining quota | n/a | n/a | This component is the loading state | n/a | Replaced by a message banner naming what failed |
| Layout | Top bar 48px with the product name in Plex Serif and cobalt navigation links (current page: ink, 2px cobalt underline, `aria-current`); content on paper; side panel 560px | Skip link "Skip to content" as first focus stop | n/a | Page-level skeleton | Not-found page in the layout | Error page in the layout, no stack trace |

## 8. How the tokens are consumed

One source, generated outputs, no hand copies.

1. **Source:** `_docs/design/tokens.json` (this issue). It is the only place a token value is edited.
2. **Generator:** a small script with no new dependency (Python standard library or a Node built-in, chosen in #31)
   reads the file, resolves aliases and writes **CSS custom properties** on `:root`, named `--isc-<group>-<token>`,
   for example:

   ```css
   :root {
     --isc-color-ink: #1B1B1A;
     --isc-color-brick: #A3361F;
     --isc-status-missing-fg: var(--isc-color-brick);
     --isc-font-family-serif: "IBM Plex Serif", Georgia, "Times New Roman", "IBM Plex Sans JP", …, serif;
     --isc-space-3: 8px;
   }
   ```

   Generated files start with a "generated from `_docs/design/tokens.json`, do not edit" header.
3. **Web frontend (#31):** imports the generated `tokens.css` once at the app root; components use only `var(--isc-…)`
   names, never raw values. The `@font-face` rules point at the self-hosted WOFF2 files.
4. **Server-side PDF (#39, #40):** the WeasyPrint templates link the **same generated `tokens.css`**, plus a print
   stylesheet (`@page` size, margins, running header and footer) and `@font-face` rules pointing at local font files.
   WeasyPrint supports CSS custom properties in its current releases; #39 confirms it on the pinned version. If it does
   not, the generator also writes a resolved variant (same values, `var()` replaced by values) from the same source.
5. **Build contexts:** the Docker builds use `./frontend` and `./backend` as contexts and cannot read `_docs/`. The
   generator therefore writes its output into each consumer (for example `frontend/src/styles/tokens.css` and a
   template directory under `backend/`), the generated files are committed, and a check (`make lint` or CI) regenerates
   them and fails if they differ from what is committed. So both media consume the same file, and drift is caught.
   Exact paths and the check are decided in #31 (and its CI wiring in an `OPS:` issue if needed).

## 9. Layout and compact density

- **Base size 14px, rows 32px**, cell padding 4px 8px, line height 1.35 in tables, 1.5 in prose and quotes. Hairlines
  between rows, a 2px ink rule above each section title; 24px between sections.
- **Workspace list:** a dense table with sticky header, sortable columns (supplier, country, sector, last refresh,
  facts still proposed, flags as micro-labels), a checkbox column for choosing profiles to compare. Selected rows:
  cobalt-tint, 3px cobalt bar on the left, checked checkbox.
- **Supplier card (F5):** opens as a 560px side panel on the right. Header: supplier name (Plex Serif 24px), website
  (cobalt link), country, sector, last refresh, the source-content deletion date, and the count of facts still
  proposed; flag banners right under it. Then sections, each with fact rows, then the assessment.
- **Evidence margin note:** at 1440px and wider, the note opens as a 300px column beside the card (the panel grows by
  that width), aligned with the fact it belongs to. Below 1440px it opens inline, directly under the fact row, with the
  same paper-margin background and rule. The exact behaviour is settled in the #5 mock-up.
- **Comparison (F5):** the first column holds field labels (200px, sticky); 2 to 4 profiles appear as equal columns
  (minimum 220px) aligned row by row; 5 or more switch to a compact matrix with horizontal scroll and the label column
  sticky. Every value keeps its source chip; missing values keep the full "No public evidence found" wording.
- **Identity chat (F1):** single column, max 72ch; the AI disclosure first; candidates shown as compact definition
  lists (name, website, country, sector, one-line description) with no score or percentage.
- **Numbers and dates:** formatted per locale (`25/10/2026` in French, `Oct 25, 2026` in English), tabular figures.
- **Keyboard:** review and comparison are fully keyboard-operable (rows by arrows, actions by Tab, chips by Enter or
  Space, panel and note closed by Escape with focus returned). Pointer targets are at least 24px.
- **PDF (F9) as a research brief:** A4 portrait for a card, A4 landscape for a comparison of 3 or 4 profiles; 18mm
  margins; running header with the supplier name in Plex Serif and a hairline; footer with generation date,
  source-content deletion date, page number and the disclaimer placeholder. Facts as rows with their status label, quote
  excerpt, source URL and date as a source line; AI sections carry "AI draft" or "reviewed by …" with their provenance.
  White page, the same tokens, no screen chrome. Detailed styling is #39 and #40.

## 10. Decisions for the owner

1. **Error colour.** Brick is reserved for missing evidence, so errors use ink with a 2px border and an "Error:"
   prefix. Alternative: a separate error hue, which would need its own contrast checks and a clear distance from brick.
2. **"insufficient sources" in ink, not brick.** It is a run outcome (collection failed), not a missing field. Brick
   could be argued, since no evidence was found; this brief keeps brick to "No public evidence found" and evidence gaps.
3. **French wording** (whole column in § 6), in particular « Aucune information publique trouvée », « Extrait
   caviardé », « éditeur du site », « entreprise individuelle (personne physique) » and « Information manquante ».
4. **Display labels for status codes** ("Proposed", "Approved", "Corrected", "Deleted"): the spec gives only the codes.
5. **CJK:** default order JP, KR, SC when the language of a quote is unknown; 400 and 600 weights for the CJK families
   (larger downloads, mitigated by `unicode-range` loading). Whether to add IBM Plex Sans Arabic, Hebrew, Thai or
   Devanagari (OFL) instead of relying on system fonts for those scripts.
6. **Font subsetting and the Reserved Font Name** (§ 2, Claude addition): use IBM's own distributed subsets.
7. **Token outputs inside `frontend/` and `backend/`** with a sync check (§ 8, point 5), because the Docker build
   contexts cannot read `_docs/`.
8. **Dark theme:** not included (§ 3).

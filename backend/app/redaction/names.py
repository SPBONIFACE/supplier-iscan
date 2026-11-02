"""Deterministic name rules around the NER (#19): capitals, honorifics, labels, noise.

NER misses names written in capitals or split over a line, and flags standards ("ISO 9001") and
sentence-initial words ("Registered", "Price"). This module adds:
- `restore_case`: a copy of the text with ALL-CAPS words capitalised, same offsets, for a second
  NER pass;
- `extend`: grow a detected span over adjacent name tokens (capitals, particles, line break);
- `rule_spans`: honorific ("M. Thierry Vasseur") and label ("Contact: JEAN DUPONT") rules;
- the word lists that say what is not a name.
"""

import re
import unicodedata
from typing import Final

Span = tuple[int, int]


def fold(text: str) -> str:
    """Lower case without accents."""
    return "".join(
        char.casefold()
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )


def _words(raw: str) -> frozenset[str]:
    return frozenset(fold(word) for word in raw.split())


WORD: Final = re.compile(r"[^\W\d_]+(?:[-'’‐][^\W\d_]+)*\.?")
_PREV: Final = re.compile(r"([^\W\d_]+(?:[-'’‐][^\W\d_]+)*\.?)([ \t]*\n?[ \t]*)$")
_GAP: Final = re.compile(r"[ \t]*(?:\n[ \t]*)?")

ROLES: Final = _words(
    """chief executive officer ceo cfo cto coo cio director managing general manager
    finance financial operations technical sales marketing purchasing procurement human resources
    commercial quality sustainability legal senior technology information vorstandsvorsitzende
    finanzvorstand prokurist the our der die das dem des ein eine los las il lo gli un une una
    president chairman chairwoman chair founder co-founder cofounder owner partner head vice vp
    deputy secretary treasurer board member mr mrs ms miss dr prof professor sir madam mx
    directeur directrice général générale président présidente gérant gérante fondateur
    fondatrice pdg dg m mme mlle me responsable
    geschäftsführer geschäftsführerin vorstand vorsitzender vorsitzende inhaber inhaberin gründer
    gründerin herr frau leiter leiterin
    directora gerente fundador fundadora consejero consejera delegado delegada
    sr sra srta don doña
    amministratore amministratrice delegato delegata direttore direttrice fondatore
    fondatrice signor signora sig dott
    and et und y e of de la le"""
)
PARTICLES: Final = _words(
    "von van der den de del della di da dos du la le bin al el ben ter ten zu zur af d l"
)
STANDARDS: Final = _words(
    """iso iec en din nf astm iatf ohsas bs ansi ieee vda sae ul ce reach rohs gdpr dsgvo rgpd
    ts ecovadis csrd cdp sbti hacc brc ifs fsc pefc gmp haccp ppap fmea tisax
    gri iva tva mwst ust vat siren siret lei hrb hra duns isin iban ein nif cif uid kbis naf ape
    exw fca cpt cip dap dpu ddp fas fob cfr cif incoterms eur usd gbp chf ebitda"""
)
# Words that are not names when they start a detected span (sentence-initial and heading words
# of the supported languages). A real surname after a first name or honorific is kept: these
# are dropped from the front of a span, never from its tail.
COMMON: Final = _words(
    """registered office price prices call contact contacts our this these that we you your
    certifications delivery anruf hauptnummer lieferbedingungen
    annual total quality terms payment delivery address phone email tel fax company
    report certificate certified certification standard standards product products services
    service customer customers about welcome please see read more new all for from with signed
    signature date page section article table figure annex appendix summary overview key facts
    history legal notice privacy policy imprint copyright conditions revenue turnover employees
    staff headcount founded established located based number registration capital share
    shareholders ownership group management mission vision values sustainability environment
    health safety supplier suppliers procurement compliance audit audits insurance insured
    tax vat bank banking accounts accounting financial statements results year years month
    first second third last next previous current introduction conclusion note notes
    signé signée prix appel appeler appelez siège social société adresse téléphone courriel
    notre nos votre vos les des une mentions légales politique propos bienvenue accueil produits
    clients chiffre affaires effectif effectifs fondée créée qualité certifié certifiée
    résumé annexe tableau cordialement merci bonjour générales vente
    unterschrift unterzeichnet gezeichnet preis preise anruf rufen sitz firmensitz anschrift
    telefon unser unsere unseren umsatz mitarbeiter gegründet zertifikat qualität
    datenschutz kontakt über uns willkommen impressum bedingungen zahlung lieferung hinweis
    firmado precio precios llamar llame domicilio sede dirección teléfono nuestra nuestro
    nuestros ingresos facturación empleados fundada certificado calidad aviso política contacto
    sobre nosotros bienvenido saludos resumen anexo tabla condiciones pago entrega
    firmato prezzo prezzi chiamare chiama indirizzo nostra nostro nostri fatturato dipendenti
    fondata certificato qualità informativa contatto siamo benvenuti saluti sintesi allegato
    tabella condizioni pagamento consegna cordiali distinti"""
)
LABEL_WORDS: Final = _words(
    """contact contacto contatto kontakt ansprechpartner ansprechpartnerin signed signé signée
    firmado firmato unterschrift auteur author autor autore name nom nombre nome by par
    por da persona personne person referente"""
)
ROLES_EXTRA: Final = _words(
    """achats ventes einkauf vertrieb compras ventas acquisti vendite comptable comptabilité
    buchhaltung contabilidad contabilità ressources humaines personal rrhh risorse umane
    commerciale comercial verkauf produktion production producción produzione
    calidad finanzas finanza finances finanzen informatique logistique
    logistik logistica logistics ingénieur ingeniería engineer engineering ingegnere
    assistant assistante assistent assistente representative representante vertreter
    team équipe abteilung département department servicio servizio client
    kundendienst atención cliente clientes servicios buyer buyers acheteur
    acheteuse einkäufer comprador compradora aufsichtsrat conseil consejo consiglio council
    committee comité comitato ausschuss"""
)
COMPANY: Final = _words(
    """sa sas sasu sarl eurl sci gmbh ag kg ohg se ug ltd limited llc llp lp inc corp
    corporation plc bv nv spa srl sl slu ab oy as aps co company holding holdings group gruppe
    groupe bank partners industries technologies solutions services components logistics
    textiles systems manufacturing supplies trading capital energy steel"""
)

_HONORIFIC_WORDS: Final = (
    "M. Mme Mlle Mr Mr. Mrs Mrs. Ms Ms. Dr Dr. Prof Prof. Herr Frau Sr Sr. Sra Sra. Srta Srta. "
    "Sig Sig. Sig.ra Sig.na Dott Dott. Dott.ssa Monsieur Madame Mademoiselle Maître Señor "
    "Señora Signor Signora Don Doña Dña Dña. Professeur Docteur Mister Miss Mx Mx."
).split()
_HONORIFIC_ALTERNATIVES: Final = "|".join(
    sorted(
        {re.escape(word) for word in _HONORIFIC_WORDS}
        | {re.escape(word.upper()) for word in _HONORIFIC_WORDS},
        key=len,
        reverse=True,
    )
)
_HONORIFIC: Final = re.compile(
    rf"(?<![\w.])(?:{_HONORIFIC_ALTERNATIVES})(?![^\W\d_])[ \t]*\n?[ \t]*"
)

_BLANKS: Final = r"[ \t]*(?:\n[ \t]*){0,2}"
_LABELS: Final = (
    r"contact(?:\s+person)?|personne\s+de\s+contact|contact\s+commercial|contacto|"
    r"persona\s+de\s+contacto|contatto|persona\s+di\s+riferimento|referente|"
    r"ansprechpartner(?:in)?|ansprechperson|kontakt(?:person)?|sign[ée]e?(?:\s+par)?|signed|"
    r"signature|signataire|unterschrift|unterzeichnet\s+von|gezeichnet|firmado(?:\s+por)?|"
    r"firma|firmato(?:\s+da)?|prepared\s+by|written\s+by|author|auteur|autor|autore|"
    r"verfasser|representative|repr[ée]sentant|vertreter|attn|attention|name|nom|nombre|nome"
)
_BY_LABELS: Final = (
    r"signed\s+by|sign[ée]e?\s+par|firmado\s+por|firmato\s+da|unterzeichnet\s+von|"
    r"prepared\s+by|written\s+by"
)
_CLOSINGS: Final = (
    r"best\s+regards|kind\s+regards|regards|sincerely|yours\s+sincerely|cordialement|"
    r"bien\s+cordialement|mit\s+freundlichen\s+gr(?:ü|ue)(?:ß|ss)en|"
    r"freundliche\s+gr(?:ü|ue)(?:ß|ss)e|saludos|atentamente|cordiali\s+saluti|distinti\s+saluti"
)
_LABEL: Final = re.compile(
    rf"(?<!\w)(?:(?:{_LABELS})\s*:|(?:{_BY_LABELS})(?=\s)|(?:{_CLOSINGS})\s*[,.!]?){_BLANKS}",
    re.IGNORECASE,
)


def _kind(body: str) -> str:
    """`caps` (ALL CAPS, two letters or more), `cap` (starts upper case) or `low`."""
    if sum(c.isalpha() for c in body) >= 2 and body.isupper():
        return "caps"
    if body[:1].isupper() or _ELIDED.match(body):
        return "cap"
    return "low"


_ELIDED: Final = re.compile(r"[dl]['’][A-ZÀ-ÝŒ]")


def _is_particle(body: str) -> bool:
    """A name particle (de, von, van der ...), in lower case or in capitals."""
    return fold(body) in PARTICLES and _kind(body) in ("low", "caps")


def _body(token: str) -> str:
    """The token without a final full stop, unless it is an initial ("J.")."""
    return token[:-1] if token.endswith(".") and len(token) > 2 else token


def _is_initial(token: str) -> bool:
    return len(token) == 2 and token[0].isupper() and token.endswith(".")


def not_a_name(key: str, *, common: bool) -> bool:
    """True for a folded word that is a role, company word, standard, label or (if `common`) a
    common sentence-initial word."""
    if key in ROLES or key in ROLES_EXTRA or key in COMPANY or key in STANDARDS:
        return True
    return key in LABEL_WORDS or (common and key in COMMON)


def restore_case(text: str) -> str:
    """Capitalise ALL-CAPS words (a second NER view of the text); offsets are unchanged."""

    def fix(match: re.Match[str]) -> str:
        token = match.group()
        if match.end() < len(text) and text[match.end()].isdigit():
            return token
        body = _body(token)
        key = fold(body)
        if _kind(body) != "caps" or key in STANDARDS:
            return token
        if key in PARTICLES:
            fixed = body.lower()
        else:
            fixed = re.sub(r"[^\W\d_]+", lambda m: m.group()[0] + m.group()[1:].lower(), body)
        return fixed + token[len(body) :] if len(fixed) == len(body) else token

    return WORD.sub(fix, text)


def _candidate(match: re.Match[str], text: str, *, common: bool) -> bool:
    """Whether a word right after a name can be part of it."""
    token = match.group()
    key = fold(_body(token))
    if match.end() < len(text) and text[match.end()].isdigit():
        return False
    return key not in PARTICLES and not not_a_name(key, common=common)


def extend(text: str, span: Span) -> Span:
    """Grow a detected name over adjacent capitalised or ALL-CAPS tokens and particles."""
    start, end = span
    tokens = list(WORD.finditer(text, start, end))
    names = [m for m in tokens if fold(_body(m.group())) not in PARTICLES]
    single = len(names) <= 1
    added, position = 0, end
    while added < 2:
        gap = _GAP.match(text, position)
        match = WORD.match(text, gap.end()) if gap is not None and gap.end() > position else None
        if gap is None or match is None:
            break
        newline = "\n" in gap.group()
        body = _body(match.group())
        kind = _kind(body)
        if _is_particle(body):
            position = match.end()
            continue
        if not _candidate(match, text, common=not (single and not newline)):
            break
        if newline and not single:
            break
        if kind == "caps" or (kind == "cap" and not newline and len(names) + added < 3):
            end = match.end() - (len(match.group()) - len(body))
            position = match.end()
            added += 1
        else:
            break
    first = WORD.match(text, start)
    if first is not None and (
        _kind(_body(first.group())) == "caps" or (single and end - start < 40)
    ):
        start = _extend_left(text, start)
    return start, end


def _extend_left(text: str, start: int) -> int:
    """A first name, initial or particle written just before an ALL-CAPS surname."""
    for _ in range(3):
        window = text[max(0, start - 80) : start]
        previous = _PREV.search(window)
        if previous is None or not previous.group(2):
            break
        token = previous.group(1)
        body = _body(token)
        kind = _kind(body)
        at = start - len(window) + previous.start(1)
        if _is_initial(token) or _is_particle(body):
            start = at
            continue
        probe = WORD.match(text, at)
        if kind == "cap" and probe is not None and _candidate(probe, text, common=True):
            start = at
        break
    return start


def _run(text: str, pos: int, *, limit: int, common_first: bool, minimum: int) -> Span | None:
    """The name tokens starting at `pos`: capitalised or ALL-CAPS words, initials, particles."""
    first, end, count, position = None, pos, 0, pos
    lead: int | None = None
    while count < limit:
        match = WORD.match(text, position)
        if match is None or (match.end() < len(text) and text[match.end()].isdigit()):
            break
        token = match.group()
        body = _body(token)
        key = fold(body)
        if _is_particle(body):
            lead = match.start() if lead is None and first is None else lead
        elif _kind(body) == "low":
            break
        else:
            if key in PARTICLES or not_a_name(key, common=common_first and first is None):
                break
            first = (lead if lead is not None else match.start()) if first is None else first
            end = match.end() - (len(token) - len(body))
            count += 1
            if body != token:
                break  # a full stop closes the name
        gap = _GAP.match(text, match.end())
        if gap is None or gap.end() == match.end():
            break
        position = gap.end()
    if first is None or count < minimum:
        return None
    following = WORD.match(text, _skip_blank(text, end))
    if following is not None and fold(_body(following.group())) in COMPANY:
        return None
    if any(fold(_body(m.group())) in COMPANY for m in WORD.finditer(text, first, end)):
        return None
    return first, end


def _skip_blank(text: str, position: int) -> int:
    while position < len(text) and text[position] in " \t":
        position += 1
    return position


_STREETS: Final = (
    r"rue|avenue|boulevard|bd|via|viale|piazza|corso|calle|plaza|paseo|avenida|street|road|"
    r"lane|way|platz|weg|allee|chemin|impasse|place|quai|carrer|rua"
)
_CAP_WORD: Final = r"[A-ZÀ-ÝŒ][\w'’-]*"
_PROTECTED: Final = re.compile(
    rf"(?<!\w)(?:{_STREETS})\.?[ \t]+{_CAP_WORD}(?:[ \t]+{_CAP_WORD}){{0,3}}[ \t]*,?[ \t]*\d+"
    rf"|(?<!\w)[^\W\d_]+(?:stra(?:ß|ss)e|str\.|gasse|allee|platz|weg)[ \t]*\d+"
    r"|(?<!\w)(?:registered\s+office|head\s+office|office|si[èe]ge(?:\s+social)?|sede(?:\s+legale)?"
    r"|sitz|firmensitz|domicile|domicilio(?:\s+social)?|address|adresse|anschrift|indirizzo"
    r"|direcci[óo]n)[ \t]*:[^\n]*"
    r"|(?<!\w)(?:sign[ée]e?|fait|firmado|firmato|signed|gezeichnet|done|unterschrieben)"
    rf"[ \t]+(?:à|a|en|in|at)[ \t]+{_CAP_WORD}(?:[ \t-]+{_CAP_WORD})?"
    r"|(?<!\w)(?:EXW|FCA|CPT|CIP|DAP|DPU|DDP|FAS|FOB|CFR|CIF)"
    rf"[ \t]+{_CAP_WORD}(?:[ \t]+{_CAP_WORD})?",
    re.IGNORECASE,
)


def protected_spans(text: str) -> list[Span]:
    """Addresses, signing places and incoterm places: a place is not a person."""
    return [m.span() for m in _PROTECTED.finditer(text)]


def rule_spans(text: str) -> list[Span]:
    """Names that follow an honorific (surname included) or a label such as "Contact:"."""
    spans: list[Span] = []
    for match in _HONORIFIC.finditer(text):
        run = _run(text, match.end(), limit=4, common_first=False, minimum=1)
        if run:
            spans.append(run)
    for match in _LABEL.finditer(text):
        run = _run(text, match.end(), limit=4, common_first=True, minimum=2)
        if run:
            spans.append(run)
    return [*spans, *_table_spans(text), *_name_role_spans(text)]


_NOT_ROLE_HEADS: Final = _words("eine miss madam herr frau dott team equipe")


def _name_role_spans(text: str) -> list[Span]:
    """ "Imogen Cranmoor, Purchasing Director": two or more name tokens, then a role."""
    spans: list[Span] = []
    position = 0
    for match in WORD.finditer(text):
        if (
            match.start() < position
            or _kind(_body(match.group())) == "low"
            or _is_particle(_body(match.group()))
        ):
            continue
        run = _run(text, match.start(), limit=3, common_first=True, minimum=2)
        if run is None:
            continue
        position = run[1]
        tail = re.compile(r"[ \t]*[,;|–—-]?[ \t]*(?:\n[ \t]*)?").match(text, run[1])
        role = WORD.match(text, tail.end()) if tail is not None else None
        key = fold(_body(role.group())) if role is not None else ""
        if len(key) > 3 and key in (ROLES | ROLES_EXTRA) and key not in _NOT_ROLE_HEADS:
            spans.append(run)
    return spans


_NAME_HEADERS: Final = _words(
    """name nom nombre nome contact kontakt contacto contatto person personne persona
    ansprechpartner prénom vorname nachname apellido cognome"""
)
_CELL_SPLIT: Final = re.compile(r"\||\t")


def _cells(line: str) -> list[Span]:
    parts: list[Span] = []
    previous = 0
    for cell in _CELL_SPLIT.finditer(line):
        parts.append((previous, cell.start()))
        previous = cell.end()
    parts.append((previous, len(line)))
    return [(a, b) for a, b in parts if line[a:b].strip()]


def _table_spans(text: str) -> list[Span]:
    """In a table whose header names a name column, the cells of that column."""
    spans: list[Span] = []
    column: int | None = None
    offset = 0
    for line in text.split("\n"):
        if "|" not in line and "\t" not in line:
            column = None
        else:
            parts = _cells(line)
            header = [
                i
                for i, (a, b) in enumerate(parts)
                if WORD.search(line, a, b)
                and all(fold(_body(w.group())) in _NAME_HEADERS for w in WORD.finditer(line, a, b))
            ]
            if header:
                column = header[0]
            elif column is not None and column < len(parts):
                a, b = parts[column]
                cell_start = offset + a + (len(line[a:b]) - len(line[a:b].lstrip()))
                run = _run(text, cell_start, limit=4, common_first=True, minimum=1)
                if run and run[1] <= offset + b:
                    spans.append(run)
        offset += len(line) + 1
    return spans

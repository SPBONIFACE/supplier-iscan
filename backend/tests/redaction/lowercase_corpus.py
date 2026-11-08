"""Lower-case names with a clue next to them, and lower-case prose that must not be touched (#19).

Names come from `NAMES_B`, written in lower case inside clue templates (title or label before the
name, job title after it). `LOWER_PROSE` is ordinary lower-case text in the same shapes (a label or
an honorific followed by plain words): nothing in it may change. Synthetic text.
"""

from tests.redaction.name_corpus import NAMES_B

# language -> templates; {f} first name, {l} surname
CLUE_TEMPLATES: dict[str, tuple[str, ...]] = {
    "en": (
        "contact: {f} {l}",
        "signed by {f} {l}",
        "{f} {l}, head of purchasing",
        "mr {l} will call back",
        "dr. {l} chairs the committee",
    ),
    "fr": (
        "contact : {f} {l}",
        "signé par {f} {l}",
        "{f} {l}, directeur achats",
        "m. {l} rappellera demain",
        "mme {l} est absente",
    ),
    "de": (
        "ansprechpartner: {f} {l}",
        "{f} {l}, leiter einkauf",
        "herr {l} ruft zurück",
        "frau {l} ist abwesend",
    ),
    "es": (
        "contacto: {f} {l}",
        "firmado por {f} {l}",
        "{f} {l}, director de compras",
        "sr. {l} llamará mañana",
    ),
    "it": (
        "contatto: {f} {l}",
        "firmato da {f} {l}",
        "{f} {l}, direttore acquisti",
        "sig. {l} richiamerà domani",
        "dott. {l} è assente",
    ),
}


def lower_case_cases(per_language: int = 8) -> list[tuple[str, str, tuple[str, ...]]]:
    """(language, text, name parts that must disappear), names in lower case."""
    cases: list[tuple[str, str, tuple[str, ...]]] = []
    for language, templates in CLUE_TEMPLATES.items():
        firsts, lasts = NAMES_B[language]
        for index in range(per_language):
            first = firsts[index % len(firsts)].lower()
            last = lasts[(index * 3 + 1) % len(lasts)].lower()
            template = templates[index % len(templates)]
            used = (first, last) if "{f}" in template else (last,)
            parts = tuple(p for item in used for p in item.split() if len(p) > 3)
            cases.append((language, template.format(f=first, l=last), parts))
    return cases


LOWER_PROSE: tuple[str, ...] = (
    "contact: our sales team",
    "contact: sales department",
    "contact: customer service",
    "contact: via email or phone",
    "contact: by phone",
    "contact: the head office",
    "contact: please call us",
    "contact: reception desk",
    "signed by the director",
    "signed by both parties",
    "signed by hand",
    "head of purchasing",
    "the purchasing director, head of the group",
    "the team, manager approval required",
    "contact : notre service commercial",
    "contact : le service achats",
    "contact : par téléphone ou par courriel",
    "signé par le directeur",
    "signé par les deux parties",
    "signé par voie électronique",
    "le directeur général, directeur du groupe",
    "ansprechpartner: unser vertrieb",
    "ansprechpartner: der einkauf",
    "ansprechpartner: per telefon oder e-mail",
    "kontakt: unser kundendienst",
    "contacto: nuestro equipo comercial",
    "contacto: por teléfono o por correo",
    "firmado por el gerente",
    "firmado por ambas partes",
    "contatto: ufficio acquisti",
    "contatto: il nostro servizio clienti",
    "firmato dal direttore",
    "firmato da entrambe le parti",
    "regards, the team",
    "best regards, customer support",
    "cordialement, l'équipe achats",
    "kind regards, sales team",
    "l'acheteur, directeur des achats",
    "5 m. long and 3 m. wide",
    "it takes 10 ms. latency is low",
    "the shipment, director of logistics approval pending",
)

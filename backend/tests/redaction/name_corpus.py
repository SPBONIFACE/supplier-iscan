"""Generated synthetic corpus of invented people for redaction recall (#19).

Per language, invented first names and surnames (some with accents, hyphens, particles) are
placed in six contexts (signature, Contact line, bullet list, prose, table, line-broken) in three
casings (normal, "Jean DUPONT", ALL CAPS). `NON_PERSON` is a realistic set of text without any
person: nothing in it may change. Use `NAMES_A` (development) and `NAMES_B` (fresh, never used to
tune rules).
"""

from dataclasses import dataclass

CASINGS = ("normal", "surname_caps", "all_caps")
CONTEXTS = ("signature", "contact", "bullet", "prose", "table", "linebroken")

# language -> (first names, surnames); invented combinations, no real person intended.
NAMES_A: dict[str, tuple[list[str], list[str]]] = {
    "en": (
        ["Gareth", "Imogen", "Rupert", "Fiona", "Lachlan", "Davina", "Alistair", "Marguerite"],
        [
            "Pellingham",
            "Ashgrove",
            "Thornbury",
            "Wetherell",
            "Cranmoor",
            "O'Halloran",
            "Stanhope",
            "Brightwell",
        ],
    ),
    "fr": (
        [
            "Étienne",
            "Solène",
            "Gaspard",
            "Mathilde",
            "Anselme",
            "Clémence",
            "Jean-Baptiste",
            "Aurélien",
        ],
        [
            "Marchetti",
            "Delaunay",
            "Fontanel",
            "Vasseur",
            "Quentin-Lacroix",
            "Beaumarchais",
            "de Lestrade",
            "Rouvière",
        ],
    ),
    "de": (
        ["Wolfram", "Annegret", "Dietmar", "Henrike", "Ottmar", "Gudrun", "Lennart", "Sieglinde"],
        [
            "Hartwig",
            "Blumenthal",
            "Kesselring",
            "Aschenbach",
            "von Treuenfels",
            "Wiedemann",
            "Langenscheidt",
            "Östreich",
        ],
    ),
    "es": (
        ["Rodrigo", "Itziar", "Baltasar", "Encarnación", "Joaquín", "Marisol", "Ignacio", "Leonor"],
        [
            "Valdivieso",
            "Montenegro",
            "Carrasquilla",
            "del Olmo",
            "Echeverría",
            "Saavedra",
            "Villanueva",
            "Zubiría",
        ],
    ),
    "it": (
        [
            "Ludovico",
            "Graziella",
            "Tommaso",
            "Ottavia",
            "Fabrizio",
            "Elisabetta",
            "Corrado",
            "Violante",
        ],
        [
            "Bellandi",
            "Cavalcanti",
            "Montefiori",
            "della Rovere",
            "Santangelo",
            "Perugini",
            "Baldassarre",
            "Lombardozzi",
        ],
    ),
}
NAMES_B: dict[str, tuple[list[str], list[str]]] = {
    "en": (
        [
            "Hamish",
            "Octavia",
            "Percival",
            "Rosalind",
            "Barnaby",
            "Cordelia",
            "Tristram",
            "Philippa",
        ],
        [
            "Longbottom-Reed",
            "Fairclough",
            "Hollingworth",
            "Mortimer",
            "Pennywhistle",
            "Dunstable",
            "Glenavy",
            "Quartermain",
        ],
    ),
    "fr": (
        [
            "Thibault",
            "Ségolène",
            "Maxence",
            "Apolline",
            "Évariste",
            "Bérénice",
            "Pierre-Louis",
            "Gwenaëlle",
        ],
        [
            "Lavergne",
            "Castellane",
            "Duvernois",
            "Montrichard",
            "Sauvageot",
            "Le Gallic",
            "d'Aubigny",
            "Tessier-Roux",
        ],
    ),
    "de": (
        [
            "Konstantin",
            "Brunhilde",
            "Raimund",
            "Waltraud",
            "Friedhelm",
            "Isolde",
            "Ansgar",
            "Hannelore",
        ],
        [
            "Rosenbaum",
            "Fürstenberg",
            "Eichhorn",
            "Grünewald",
            "van der Heyden",
            "Wallenstein",
            "Reinhardt-Voss",
            "Zielinski",
        ],
    ),
    "es": (
        [
            "Teodoro",
            "Almudena",
            "Casimiro",
            "Esperanza",
            "Wenceslao",
            "Remedios",
            "Aurelio",
            "Soledad",
        ],
        [
            "Barrientos",
            "Quintanilla",
            "de la Cuadra",
            "Mondragón",
            "Arrieta",
            "Cifuentes",
            "Salvatierra",
            "Ibarguren",
        ],
    ),
    "it": (
        [
            "Raimondo",
            "Eleonora",
            "Giacinto",
            "Beatrice",
            "Sebastiano",
            "Costanza",
            "Amedeo",
            "Liliana",
        ],
        [
            "Pellegrini-Rota",
            "Ventimiglia",
            "Castiglioni",
            "di Bartolo",
            "Malaspina",
            "Gentiloni",
            "Ruspoli",
            "Tagliaferri",
        ],
    ),
}

ROLES = {
    "en": "Purchasing Director",
    "fr": "Directeur des achats",
    "de": "Leiter Einkauf",
    "es": "Director de compras",
    "it": "Direttore acquisti",
}
HONORIFICS = {
    "en": ("Mr", "Dr", "Ms"),
    "fr": ("M.", "Mme", "Dr"),
    "de": ("Herr", "Frau", "Dr."),
    "es": ("Sr.", "Sra.", "Dr."),
    "it": ("Sig.", "Sig.ra", "Dott."),
}
LABELS = {
    "en": ("Contact", "Signed by"),
    "fr": ("Contact", "Signé par"),
    "de": ("Ansprechpartner", "Kontakt"),
    "es": ("Contacto", "Firmado por"),
    "it": ("Contatto", "Firmato da"),
}
PROSE = {
    "en": "The offer was reviewed by {n} before the audit of the plant.",
    "fr": "L'offre a été examinée par {n} avant l'audit de l'usine.",
    "de": "Das Angebot wurde von {n} vor dem Audit des Werks geprüft.",
    "es": "La oferta fue revisada por {n} antes de la auditoría de la planta.",
    "it": "L'offerta è stata esaminata da {n} prima dell'audit dello stabilimento.",
}
CLOSING = {
    "en": "Best regards,",
    "fr": "Cordialement,",
    "de": "Mit freundlichen Grüßen",
    "es": "Saludos cordiales,",
    "it": "Cordiali saluti,",
}


@dataclass(frozen=True)
class NameCase:
    language: str
    context: str
    casing: str
    text: str
    name_parts: tuple[str, ...]
    role: str


def _styled(first: str, last: str, casing: str) -> tuple[str, str]:
    if casing == "surname_caps":
        return first, last.upper()
    if casing == "all_caps":
        return first.upper(), last.upper()
    return first, last


def _render(language: str, context: str, first: str, last: str) -> str:
    name = f"{first} {last}"
    role = ROLES[language]
    label = LABELS[language][0]
    return {
        "signature": f"{CLOSING[language]}\n{name}\n{role}\nHalden Components Ltd",
        "contact": f"{label}: {name}, {role}",
        "bullet": f"Management team:\n- {name}, {role}\n- Halden Components Ltd, head office",
        "prose": PROSE[language].format(n=name),
        "table": f"Name | Position\n{name} | {role}",
        "linebroken": f"{first}\n{last}\n{role}",
    }[context]


def name_cases(
    names: dict[str, tuple[list[str], list[str]]], per_language: int = 8
) -> list[NameCase]:
    cases: list[NameCase] = []
    for language, (firsts, lasts) in names.items():
        for index in range(per_language):
            first, last = firsts[index % len(firsts)], lasts[(index * 3 + 1) % len(lasts)]
            for context in CONTEXTS:
                for casing in CASINGS:
                    styled_first, styled_last = _styled(first, last, casing)
                    parts = tuple(
                        part
                        for part in f"{first} {last}".replace("'", " ").split()
                        if part.lower()
                        not in {"de", "la", "del", "della", "di", "von", "van", "der", "le", "d"}
                    )
                    cases.append(
                        NameCase(
                            language,
                            context,
                            casing,
                            _render(language, context, styled_first, styled_last),
                            parts,
                            ROLES[language],
                        )
                    )
    return cases


def honorific_cases(
    names: dict[str, tuple[list[str], list[str]]], per_language: int = 8
) -> list[NameCase]:
    """ "M. Thierry Vasseur" and "Mme FONTAINE": no surname may leak after an honorific."""
    cases: list[NameCase] = []
    for language, (firsts, lasts) in names.items():
        for index in range(per_language):
            first, last = firsts[index % len(firsts)], lasts[(index * 3 + 1) % len(lasts)]
            honorific = HONORIFICS[language][index % 3]
            for casing, text_name, parts in (
                ("normal", f"{first} {last}", (first, last)),
                ("surname_caps", f"{first} {last.upper()}", (first, last)),
                ("surname_only", last.upper(), (last,)),
                ("surname_only_normal", last, (last,)),
            ):
                cases.append(
                    NameCase(
                        language,
                        "honorific",
                        casing,
                        PROSE[language].format(n=f"{honorific} {text_name}"),
                        tuple(
                            p
                            for part in parts
                            for p in part.replace("'", " ").split()
                            if p.lower()
                            not in {
                                "de",
                                "la",
                                "del",
                                "della",
                                "di",
                                "von",
                                "van",
                                "der",
                                "le",
                                "d",
                            }
                        ),
                        "",
                    )
                )
    return cases


# Text without any person; every line must come out unchanged.
NON_PERSON: tuple[str, ...] = (
    "ISO 9001:2015, ISO 14001",
    "The plant is certified to ISO 9001:2015 and ISO 14001:2015 since 2019.",
    "Certifications: IATF 16949, EN 10204 3.1, DIN EN ISO 13485, NF EN 1090, ASTM A36.",
    "Registered office: 12 Industrial Way, Leeds LS1 4AB",
    "Registered office",
    "Price",
    "Prices are quoted in EUR, excluding VAT.",
    "Call us on weekdays between nine and five.",
    "Signé",
    "Signé à Lyon, le 4 mars 2025.",
    "Siège social : 8 rue de la Paix, 75002 Paris",
    "Prix hors taxes, départ usine.",
    "Appelez-nous du lundi au vendredi.",
    "Notre société emploie 340 personnes.",
    "Chiffre d'affaires 2024 : 48,2 millions d'euros.",
    "Mentions légales",
    "Firmensitz: Hauptstraße 5, 10115 Berlin",
    "Preis ab Werk, zuzüglich Mehrwertsteuer.",
    "Unterschrift",
    "Unser Unternehmen beschäftigt 340 Mitarbeiter.",
    "Anruf unter der Hauptnummer.",
    "Domicilio social: Calle Mayor 3, 28013 Madrid",
    "Precio sin IVA, puesto en fábrica.",
    "Firmado en Madrid el 4 de marzo de 2025.",
    "Llame a nuestro departamento comercial.",
    "Nuestra empresa cuenta con 340 empleados.",
    "Sede legale: Via Roma 10, 20121 Milano",
    "Prezzo franco fabbrica, IVA esclusa.",
    "Firmato a Milano il 4 marzo 2025.",
    "Chiamare il reparto acquisti.",
    "La nostra azienda impiega 340 persone.",
    "Contact us for a quotation.",
    "About us",
    "Quality policy and environmental management system.",
    "Annual report 2024, total revenue EUR 42.5 million.",
    "Terms of payment: 30 days net.",
    "Welcome to our website.",
    "Our products are made in Germany.",
    "HEADQUARTERS AND REGISTERED OFFICE",
    "ISO 45001 AND ISO 14001 CERTIFIED",
    "PURCHASING DIRECTOR",
    "ACME GMBH",
    "GENERAL CONDITIONS OF SALE",
    "CONDITIONS GÉNÉRALES DE VENTE",
    "Total assets EUR 120 million; equity EUR 45 million.",
    "The Chief Executive Officer and the Finance Director report to the board.",
    "Le directeur général et le directeur financier rendent compte au conseil.",
    "Der Geschäftsführer und der Finanzvorstand berichten an den Aufsichtsrat.",
    "El consejero delegado y el director financiero informan al consejo.",
    "L'amministratore delegato e il direttore finanziario riferiscono al consiglio.",
    "Delivery: DAP Rotterdam, Incoterms 2020.",
    "Copyright 2025 Halden Components Ltd. All rights reserved.",
    "Privacy policy | Imprint | Contact",
    "Annex 2: List of certificates (ISO, IEC, EN).",
    "Section 3 - Health and safety (OHSAS 18001, ISO 45001).",
    "Member of the Federation of Engineering Industries since 1998.",
    "Our sustainability report follows GRI standards and the CSRD.",
    "Summary of key facts: founded 1987, 340 employees, 3 plants.",
    "Table 4: Delivery performance by quarter.",
    "Please see Annex B for the full price list.",
    "Read more about our history.",
)

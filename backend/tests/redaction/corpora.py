"""Synthetic corpora for redaction (#19): invented people only, companies that do not exist.

Each case: the text, the personal data that must be gone (`remove`), and what must survive
(`keep`: roles, company names, identifiers, figures that grounded quotes rely on).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    language: str
    text: str
    remove: tuple[str, ...]
    keep: tuple[str, ...] = ()


CORPUS: tuple[Case, ...] = (
    # --- English ---------------------------------------------------------------------------
    Case(
        "en",
        "Our Chief Executive Officer, Zoë Müller-Lüdenscheidt, joined Brightwater Holdings Ltd in "
        "2019. Write to zoe.muller@brightwater.example.",
        ("Zoë Müller-Lüdenscheidt", "zoe.muller@brightwater.example"),
        ("Chief Executive Officer", "Brightwater Holdings Ltd", "2019"),
    ),
    Case(
        "en",
        "The board is chaired by Margaret Ashworth. Finance Director Oliver Pemberton signed the "
        "accounts. Call +44 20 7946 0958 or 020 7946 0123.",
        ("Margaret Ashworth", "Oliver Pemberton", "+44 20 7946 0958", "020 7946 0123"),
        ("Finance Director",),
    ),
    Case(
        "en",
        "Founded by Daniel Whitcombe and Priya Raman, Northfield Components employs 240 people. "
        "Company number 01234567, LEI 5493001KJTIIGC8Y1R12, revenue GBP 42.5 million.",
        ("Daniel Whitcombe", "Priya Raman"),
        ("Northfield Components", "5493001KJTIIGC8Y1R12", "42.5 million"),
    ),
    Case(
        "en",
        "Contact our sustainability lead, Hannah O'Brien, at hannah.obrien@northfield.example "
        "or on (415) 555-2671.",
        ("Hannah O'Brien", "hannah.obrien@northfield.example", "(415) 555-2671"),
        ("sustainability lead",),
    ),
    Case(
        "en",
        "Chairman Thomas Fairweather retired. Marcus Delgado, Chief Financial Officer, "
        "presented the results of Lakeside Logistics PLC.",
        ("Thomas Fairweather", "Marcus Delgado"),
        ("Chief Financial Officer", "Lakeside Logistics PLC"),
    ),
    # --- French ----------------------------------------------------------------------------
    Case(
        "fr",
        "Le directeur général, François Pérez, a repris Verdier Industries SA en 2018. "
        "Écrire à francois.perez@verdier.example ou appeler le +33 1 23 45 67 89.",
        ("François Pérez", "francois.perez@verdier.example", "+33 1 23 45 67 89"),
        ("directeur général", "Verdier Industries SA"),
    ),
    Case(
        "fr",
        "La présidente, Camille Beaumont-Lefèvre, et le directeur financier Étienne Marchand "
        "dirigent le groupe. Tél : 01.42.68.53.00. SIREN 552 081 317, SIRET 552 081 317 00022.",
        ("Camille Beaumont-Lefèvre", "Étienne Marchand", "01.42.68.53.00"),
        ("présidente", "directeur financier", "552 081 317", "552 081 317 00022"),
    ),
    Case(
        "fr",
        "Fondée par Amélie Rousseau et Jean-Baptiste Colin, la société Lumière Textiles SAS "
        "emploie 85 personnes. TVA FR40 303 265 045. Contact : 06 12 34 56 78.",
        ("Amélie Rousseau", "Jean-Baptiste Colin", "06 12 34 56 78"),
        ("Lumière Textiles SAS", "FR40 303 265 045"),
    ),
    Case(
        "fr",
        "Mme Sophie Delacroix, responsable qualité, a présenté la certification ISO 9001 de "
        "Moulin Grand Est SARL.",
        ("Sophie Delacroix",),
        ("responsable qualité", "ISO 9001", "Moulin Grand Est SARL"),
    ),
    # --- German ----------------------------------------------------------------------------
    Case(
        "de",
        "Geschäftsführer Hans Schneider und Anna Müller leiten die Kranich Maschinenbau GmbH. "
        "Telefon +49 30 1234567, E-Mail hans.schneider@kranich.example.",
        ("Hans Schneider", "Anna Müller", "+49 30 1234567", "hans.schneider@kranich.example"),
        ("Geschäftsführer", "Kranich Maschinenbau GmbH"),
    ),
    Case(
        "de",
        "Der Vorstandsvorsitzende Katharina Hoffmann-Weiß verkündete den Umsatz der Berger "
        "Stahl AG: 1,2 Milliarden Euro. USt-IdNr. DE811115368. Tel. 030.123.456.",
        ("Katharina Hoffmann-Weiß", "030.123.456"),
        ("Vorstandsvorsitzende", "Berger Stahl AG", "DE811115368", "1,2 Milliarden Euro"),
    ),
    Case(
        "de",
        "Gegründet wurde das Unternehmen von Jürgen Fischer und Lena Bauer. Ansprechpartner "
        "für Einkauf ist Moritz Vogel, Telefon 0151 2345 6789.",
        ("Jürgen Fischer", "Lena Bauer", "Moritz Vogel", "0151 2345 6789"),
        ("Einkauf",),
    ),
    Case(
        "de",
        "Prokurist Stefan Wagner zeichnet für die Hartmann Logistik KG. Handelsregister "
        "HRB 123456 Amtsgericht München.",
        ("Stefan Wagner",),
        ("Prokurist", "Hartmann Logistik KG", "HRB 123456"),
    ),
    # --- Spanish ---------------------------------------------------------------------------
    Case(
        "es",
        "El director general, Carlos García Fernández, y la consejera María López dirigen "
        "Aceros del Norte SL. Correo: carlos.garcia@aceros.example, tel. +34 912 345 678.",
        (
            "Carlos García Fernández",
            "María López",
            "carlos.garcia@aceros.example",
            "+34 912 345 678",
        ),
        ("director general", "Aceros del Norte SL"),
    ),
    Case(
        "es",
        "La empresa fue fundada por Javier Ortega Ruiz y Lucía Navarro. NIF B12345678.",
        ("Javier Ortega Ruiz", "Lucía Navarro"),
        ("B12345678",),
    ),
    # --- Italian ---------------------------------------------------------------------------
    Case(
        "it",
        "L'amministratore delegato, Giulia Rossi, e il direttore Marco Bianchi guidano "
        "Ferramenta Lombarda SRL. Email giulia.rossi@ferramenta.example, tel. +39 02 1234 5678.",
        ("Giulia Rossi", "Marco Bianchi", "giulia.rossi@ferramenta.example", "+39 02 1234 5678"),
        ("amministratore delegato", "Ferramenta Lombarda SRL"),
    ),
    Case(
        "it",
        "Il presidente Alessandro Conti e la responsabile acquisti Chiara Moretti hanno firmato "
        "il bilancio. Partita IVA IT12345678901.",
        ("Alessandro Conti", "Chiara Moretti"),
        ("presidente", "IT12345678901"),
    ),
    # --- Non-Latin -------------------------------------------------------------------------
    Case(
        "zh",
        "总经理王伟和财务总监李娜负责公司运营。联系邮箱 wang.wei@hengda.example。",
        ("王伟", "李娜", "wang.wei@hengda.example"),
        ("总经理", "财务总监"),
    ),
)

# Company names NER may mislabel as people: they must survive (over-redaction ruins extraction).
COMPANY_CASES: tuple[Case, ...] = (
    Case("en", "Acme Holdings Ltd supplies Brightwater Group plc.", (), ("Acme Holdings Ltd",)),
    Case("de", "Die Siemens AG und die Kranich Maschinenbau GmbH liefern.", (), ("Siemens AG",)),
    Case("fr", "Renault SA et Verdier Industries SA sont fournisseurs.", (), ("Renault SA",)),
    Case(
        "es", "Telefónica y Aceros del Norte SL firmaron el contrato.", (), ("Aceros del Norte SL",)
    ),
    Case("it", "Fiat e Ferramenta Lombarda SRL sono partner.", (), ("Ferramenta Lombarda SRL",)),
)

# Written after the rules were tuned on CORPUS: the honest figure for unseen text.
HELD_OUT: tuple[Case, ...] = (
    Case(
        "en",
        "Managing Partner Rebecca Holloway-Grant leads Stonebridge Advisory Ltd. Reach her on "
        "+44 (0)161 496 0000 or rebecca@stonebridge.example.",
        ("Rebecca Holloway-Grant", "+44 (0)161 496 0000", "rebecca@stonebridge.example"),
        ("Managing Partner", "Stonebridge Advisory Ltd"),
    ),
    Case(
        "fr",
        "Le gérant Olivier Tessier et la directrice commerciale Inès Benali représentent "
        "Atelier du Rhône SARL. Téléphone : 04 72 00 00 00, siren 123 456 789.",
        ("Olivier Tessier", "Inès Benali", "04 72 00 00 00"),
        ("gérant", "directrice commerciale", "Atelier du Rhône SARL", "123 456 789"),
    ),
    Case(
        "de",
        "Inhaberin Sabine Kühn-Brandt und Einkaufsleiter Tobias Reuter vertreten die "
        "Nordlicht Verpackungen GmbH. Mobil: +49 171 2345678.",
        ("Sabine Kühn-Brandt", "Tobias Reuter", "+49 171 2345678"),
        ("Inhaberin", "Nordlicht Verpackungen GmbH"),
    ),
    Case(
        "es",
        "La presidenta, Isabel Moreno Castillo, y el gerente Pablo Herrera firmaron por "
        "Conservas del Sur SA. Teléfono +34 600 123 456.",
        ("Isabel Moreno Castillo", "Pablo Herrera", "+34 600 123 456"),
        ("presidenta", "gerente", "Conservas del Sur SA"),
    ),
    Case(
        "it",
        "Il direttore generale Roberto Ferrari e la dottoressa Elena Gallo guidano Cantieri "
        "Adriatici SPA. Tel. +39 06 9876 5432.",
        ("Roberto Ferrari", "Elena Gallo", "+39 06 9876 5432"),
        ("direttore generale", "Cantieri Adriatici SPA"),
    ),
)

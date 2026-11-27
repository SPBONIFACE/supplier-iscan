"""A fixed, synthetic corpus for the detector-work tests and measures (#196): no real person.

`CORPUS` maps a name to the list of texts of one run (redacted one after the other, as the
collection does). The texts are deterministic (no clock, no randomness beyond a fixed seed).
`perf_expected.json` holds what `main` redacts them to (the text itself for the small ones, its
length and sha256 for the two long ones); regenerate it only on `main`:
`uv run python -m tests.redaction.measure_perf --write-expected`.
"""

import random

MENU = (
    "Home | Products | Solutions | Sustainability | Careers | Investors | News | Contact us | "
    "Legal notice | Privacy policy | Terms of use | Sitemap | Cookie settings\n"
)
COOKIES = (
    "We use cookies to improve your experience on our website. By clicking Accept you agree to "
    "the use of all cookies. You can change your settings at any time in the cookie settings.\n"
)
FOOTER = (
    "Copyright 2026 Northwind Packaging Holding. All rights reserved. Registered office: "
    "Industriestrasse 12, 4051 Basel. Follow us on LinkedIn and YouTube.\n"
)
FIRST = ["Maria", "Jean", "Anna", "Tobias", "Chiara", "Pieter", "Sofia", "Lukas", "Elena", "Hugo"]
LAST = ["Schneider", "Dupont", "Rossi", "Reuter", "Janssen", "Moreau", "Keller", "Brandt", "Vogel"]
SENTENCES = [
    "The company produces flexible packaging for the food and pharmaceutical industries.",
    "In the financial year the group reported revenue growth of {n} percent in all regions.",
    "The audit committee reviewed the internal controls and found no material weakness.",
    "Our plants in {c} operate under the ISO 9001 and ISO 14001 management systems.",
    "The board thanks all employees for their commitment during a demanding year.",
    "Raw material prices remained volatile; the group passed on part of the increase.",
    "Greenhouse gas emissions were reduced by {n} percent against the 2019 baseline.",
    "No significant legal proceedings were pending against the company at the closing date.",
    "The supplier code of conduct applies to all direct suppliers and is part of every contract.",
    "{p} is the contact for investor relations, reachable at {m} or {t}.",
    "The report was signed by {p}, Chief Financial Officer, on behalf of the board.",
    "CONTACT: {p}, HEAD OF PURCHASING, {c}.",
    "contact: {l}, directeur achats",
    "Responsible for quality management: {p}.",
]
COUNTRIES = ["Switzerland", "Germany", "France", "Italy", "the Netherlands", "Poland"]


def _person(rng: random.Random) -> str:
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def _sentence(rng: random.Random) -> str:
    person = _person(rng)
    return rng.choice(SENTENCES).format(
        n=rng.randint(2, 19),
        c=rng.choice(COUNTRIES),
        p=person,
        l=person.lower(),
        m=f"{person.split()[0].lower()}.{person.split()[1].lower()}@northwind-pack.example",
        t=f"+41 61 {rng.randint(100, 999)} {rng.randint(10, 99)} {rng.randint(10, 99)}",
    )


def prose(size: int, seed: int) -> str:
    """Audit-report-like text of about `size` characters, with a numeric table every few pages."""
    rng = random.Random(seed)
    parts: list[str] = []
    length = 0
    page = 0
    while length < size:
        page += 1
        lines = [f"Page {page} of the annual report", MENU if page % 3 == 0 else ""]
        lines += [" ".join(_sentence(rng) for _ in range(rng.randint(3, 6))) for _ in range(4)]
        if page % 4 == 0:
            lines.append(table(rng, 20))
        block = "\n".join(line for line in lines if line) + "\n\n"
        parts.append(block)
        length += len(block)
    return "".join(parts)[:size]


def table(rng: random.Random, rows: int) -> str:
    return "\n".join(
        " ".join(f"{rng.randint(0, 99999):,}".replace(",", ".") for _ in range(8))
        for _ in range(rows)
    )


def site_pages() -> list[str]:
    rng = random.Random(7)
    pages = []
    for number in range(24):
        body = "\n".join(_sentence(rng) for _ in range(rng.randint(6, 12)))
        pages.append(f"{MENU}{COOKIES}{body}\n{FOOTER}")
    return pages


def numeric_table() -> str:
    rng = random.Random(11)
    return (
        "Key figures in thousand CHF\n" + table(rng, 400) + "\nAuditor: Pieter Janssen, Basel\n"
    )


SHORT = ["A. Writer", "2024", "-----", "Annual report 2023", "Müller", "Dupont", "", "n/a", "12 345"]


def corpus() -> dict[str, list[str]]:
    return {
        "site": site_pages(),
        "table": [numeric_table()],
        "short": list(SHORT),
        "text_40k": [prose(40_000, 1)],
        "text_200k": [prose(200_000, 2)],
    }

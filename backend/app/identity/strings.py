"""Fixed texts of the identity chat, in the two UI languages.

`DISCLOSURE` is regulatory text (AI transparency, spec § F1): it is copied character for character
from the specification, French typography included (the no-break space before the colon, the
typographic apostrophes), and `tests/identity/test_disclosure.py` asserts exact equality. Do not
reword it.

The other messages are product copy shown in the chat (not prompts: no model reads them).
"""

from typing import Literal

Language = Literal["en", "fr"]

DISCLOSURE: dict[Language, str] = {
    "en": (
        "You are talking to an AI assistant. Its role: supplier research. As AI can make "
        "mistakes, please verify the legal entity of the selected supplier and the sources "
        "provided."
    ),
    "fr": (
        "Vous échangez avec un assistant IA. Son rôle : effectuer des recherches "
        "fournisseur. L’IA pouvant faire des erreurs, veuillez vérifier l’entité "
        "légale du fournisseur sélectionné ainsi que les sources proposées."
    ),
}

MESSAGES: dict[str, dict[Language, str]] = {
    "confirm_question": {
        "en": "Is this the company you mean?",
        "fr": "Est-ce bien l’entreprise que vous cherchez ?",
    },
    "off_topic": {
        "en": "I can only help to identify the supplier. Tell me more about the company you mean.",
        "fr": (
            "Je peux seulement vous aider à identifier le fournisseur. "
            "Dites-m’en plus sur l’entreprise que vous cherchez."
        ),
    },
    "both_registries_down": {
        "en": (
            "Both public registries (Wikidata and GLEIF) are unreachable right now. "
            "You can enter the supplier's website instead."
        ),
        "fr": (
            "Les deux registres publics (Wikidata et GLEIF) sont inaccessibles pour le moment. "
            "Vous pouvez indiquer le site web du fournisseur."
        ),
    },
    "wikidata_down": {
        "en": "Wikidata is unreachable right now; the candidates come from GLEIF only.",
        "fr": "Wikidata est inaccessible pour le moment ; les candidats viennent de GLEIF seul.",
    },
    "gleif_down": {
        "en": "GLEIF is unreachable right now; the candidates come from Wikidata only.",
        "fr": "GLEIF est inaccessible pour le moment ; les candidats viennent de Wikidata seul.",
    },
    "no_candidates": {
        "en": "I found no company with this name in the public registries. "
        "You can correct the name or enter the supplier's website.",
        "fr": (
            "Je n’ai trouvé aucune entreprise de ce nom dans les registres publics. "
            "Vous pouvez corriger le nom ou indiquer le site web du fournisseur."
        ),
    },
    "agent_failed": {
        "en": (
            "The assistant could not answer this time. You can pick a candidate from the list, "
            "enter the supplier's website, or try again."
        ),
        "fr": (
            "L’assistant n’a pas pu répondre cette fois. Vous pouvez choisir un "
            "candidat dans la liste, indiquer le site web du fournisseur ou réessayer."
        ),
    },
    "website_proposal": {
        "en": "I checked the website and it responds. Is this the company you mean?",
        "fr": (
            "J’ai vérifié le site web : il répond. Est-ce bien l’entreprise que vous cherchez ?"
        ),
    },
    "website_rejected": {
        "en": "This website cannot be used: {reason}",
        "fr": "Ce site web ne peut pas être utilisé : {reason}",
    },
    "link_ignored": {
        "en": "A link in your message was ignored because it is not a valid public web address.",
        "fr": (
            "Un lien de votre message a été ignoré car ce n’est pas une adresse "
            "web publique valide."
        ),
    },
}


def disclosure_text(language: str) -> str:
    return DISCLOSURE["fr" if language == "fr" else "en"]


def message(key: str, language: str, **values: str) -> str:
    texts = MESSAGES[key]
    text = texts["fr" if language == "fr" else "en"]
    return text.format(**values) if values else text

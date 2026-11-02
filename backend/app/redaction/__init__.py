"""Personal-data redaction before any LLM call, and before storage (#19).

`RedactionGate.redact(text, ...)` returns a `RedactedText`, the only type the provider interface
accepts. Failure is `RedactionUnavailable`: nothing is sent, nothing is stored.
"""

from app.redaction.engine import RedactionContext, Redactor, get_redactor
from app.redaction.gate import RedactionGate, database_suppressed_names, gate_for
from app.redaction.text import OMISSION, RedactedText, RedactionUnavailable

__all__ = [
    "OMISSION",
    "RedactedText",
    "RedactionContext",
    "RedactionGate",
    "RedactionUnavailable",
    "Redactor",
    "database_suppressed_names",
    "gate_for",
    "get_redactor",
]

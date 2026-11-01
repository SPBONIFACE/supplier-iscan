"""The prompt set: the instructions of the LLM features, loaded at startup (#55).

The file named by PROMPT_SET_FILE is used; without that setting, the example in `app/content/`.
A configured file is a complete set that replaces the example: nothing is merged. It is validated
against `app/content/prompt-set.schema.json`, then checked per prompt id (all ids present once,
output schema, placeholders). Any problem raises `ConfigurationError` naming the file and the prompt
id, and nothing is kept.

Feature code gets text only through `PromptSet.render(prompt_id, values)`. Data (collected text,
chat turns, facts, buyer criteria, buyer context) is allowed in the data template only and is
inserted literally in one pass between fences that the value cannot contain, so it is never
expanded and never becomes instructions. Rendered text and model completions are not logged here:
`log_render` writes the id, version, set hash and size only.
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import ConfigurationError
from app.content import CONTENT_DIR, load_content_file

SCHEMA_FILE = "prompt-set.schema.json"
EXAMPLE_FILE = CONTENT_DIR / "prompt-set.example.json"
WHAT = "Prompt set file"
LANGUAGES = ("en", "fr")

logger = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Placeholders that carry collected or buyer-supplied text: data template only.
_DATA = frozenset(
    "conversation candidates supplier fields source_id source_text "
    "facts buyer_criteria buyer_context assessment".split()
)
_LANGUAGE = "language"  # a controlled value (en or fr): allowed in the instructions too


@dataclass(frozen=True)
class _Spec:
    output_schema: str
    allowed: frozenset[str]
    required: frozenset[str]


def _spec(schema: str, allowed: str, required: str) -> _Spec:
    return _Spec(schema, frozenset(allowed.split()), frozenset(required.split()))


_JUDGEMENT = "language facts buyer_criteria buyer_context"
SPECS: dict[str, _Spec] = {
    "identity": _spec(
        "IdentityProposal", "language conversation candidates", "language conversation"
    ),
    "retrieval": _spec("RetrievalResult", "supplier", "supplier"),
    "extraction": _spec("FieldExtraction", "fields source_id source_text", "fields source_text"),
    "assessment": _spec("AssessmentStatement", _JUDGEMENT, "language facts"),
    "fit": _spec("AssessmentStatement", _JUDGEMENT, "language facts buyer_criteria"),
    "recommendations": _spec("AssessmentStatement", _JUDGEMENT + " assessment", "language facts"),
}


@dataclass(frozen=True)
class RenderedPrompt:
    """The text for one call. Sensitive: never log it (`repr` hides the text)."""

    prompt_id: str
    version: str
    set_hash: str
    instructions: str = field(repr=False)
    data: str = field(repr=False)


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    instructions: str
    data_template: str
    output_schema: str


def _used(text: str) -> list[str]:
    return _PLACEHOLDER.findall(text)


@dataclass(frozen=True)
class PromptSet:
    prompts: dict[str, Prompt]
    # "sha256:<hex>" of the canonical JSON of the validated content: recorded on each run.
    content_hash: str

    def render(self, prompt_id: str, values: dict[str, str]) -> RenderedPrompt:
        """The only way feature code obtains a prompt. `values` holds exactly the placeholders the
        prompt uses; `language` must be "en" or "fr"."""
        prompt = self.prompts[prompt_id]
        used = set(_used(prompt.instructions)) | set(_used(prompt.data_template))
        unknown, missing = set(values) - used, used - set(values)
        if unknown or missing:
            raise ValueError(
                f"prompt {prompt_id!r}: values {sorted(unknown)} not used, "
                f"{sorted(missing)} missing"
            )
        if values.get(_LANGUAGE, "en") not in LANGUAGES:
            raise ValueError(f"prompt {prompt_id!r}: language must be one of {LANGUAGES}")

        def in_instructions(match: re.Match[str]) -> str:
            return values[_LANGUAGE] if match.group(1) == _LANGUAGE else match.group(0)

        def in_data(match: re.Match[str]) -> str:
            name = match.group(1)
            value = values[name]
            if name == _LANGUAGE:
                return value
            fence = "<<<"
            while fence in value:  # the value can never contain the closing fence
                fence += "<"
            return f"{fence} BEGIN {name}\n{value}\n{fence} END {name}"

        return RenderedPrompt(
            prompt_id=prompt_id,
            version=prompt.version,
            set_hash=self.content_hash,
            instructions=_PLACEHOLDER.sub(in_instructions, prompt.instructions),
            data=_PLACEHOLDER.sub(in_data, prompt.data_template),
        )


def log_render(rendered: RenderedPrompt) -> None:
    """Identification and size only: never the text."""
    logger.info(
        "Prompt rendered: id=%s version=%s set=%s chars=%d",
        rendered.prompt_id,
        rendered.version,
        rendered.set_hash,
        len(rendered.instructions) + len(rendered.data),
    )


def _content_hash(document: dict[str, Any]) -> str:
    content = {key: value for key, value in document.items() if key != "$comment"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _schema_error(path: Path, error: ConfigurationError) -> ConfigurationError:
    """Add the prompt id to a schema error that points inside a prompt."""
    match = re.search(r"at prompts/(\d+)", str(error))
    if match:
        try:
            entry = json.loads(path.read_bytes())["prompts"][int(match.group(1))]
            return ConfigurationError(f"{error} (prompt {entry.get('id')!r})")
        except (OSError, ValueError, KeyError, IndexError, AttributeError):
            pass
    return error


def _check(path: Path, entry: dict[str, Any]) -> None:
    prompt_id = entry["id"]
    label = f"{WHAT} {path} is not valid at prompts ({prompt_id!r})"
    spec = SPECS[prompt_id]
    if entry["output_schema"] != spec.output_schema:
        raise ConfigurationError(
            f"{label}: output_schema must be {spec.output_schema!r}, not {entry['output_schema']!r}"
        )
    in_instructions = set(_used(entry["instructions"]))
    used = in_instructions | set(_used(entry["data_template"]))
    declared = set(entry["placeholders"])
    for name in sorted(used | declared):
        if name not in spec.allowed:
            raise ConfigurationError(f"{label}: unknown placeholder {name!r}")
    for name in sorted(in_instructions & _DATA):
        raise ConfigurationError(
            f"{label}: placeholder {name!r} carries data and is allowed in data_template only"
        )
    if declared != used:
        raise ConfigurationError(
            f"{label}: placeholders {sorted(declared)} do not match those used {sorted(used)}"
        )
    for name in sorted(spec.required - used):
        raise ConfigurationError(f"{label}: required placeholder {name!r} is missing")


def load_prompt_set(path: Path | None = None) -> PromptSet:
    """Read and validate the file. Raises ConfigurationError naming the file and the problem."""
    path = path or EXAMPLE_FILE
    try:
        document = load_content_file(path, SCHEMA_FILE, WHAT)
    except ConfigurationError as error:
        raise _schema_error(path, error) from None
    seen: set[str] = set()
    for entry in document["prompts"]:
        if entry["id"] in seen:
            raise ConfigurationError(
                f"{WHAT} {path} is not valid at prompts: duplicate prompt id {entry['id']!r}"
            )
        seen.add(entry["id"])
    for prompt_id in SPECS:
        if prompt_id not in seen:
            raise ConfigurationError(
                f"{WHAT} {path} is not valid at prompts: prompt id {prompt_id!r} is missing"
            )
    for entry in document["prompts"]:
        _check(path, entry)
    return PromptSet(
        prompts={
            e["id"]: Prompt(
                e["id"], e["version"], e["instructions"], e["data_template"], e["output_schema"]
            )
            for e in document["prompts"]
        },
        content_hash=_content_hash(document),
    )

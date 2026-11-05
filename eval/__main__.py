"""`make eval [CONFIG=<id>|fake] [PROMPTS=<path>] [RATINGS=<csv>] [OUT=<dir>]`.

Exit codes: 0 report written, 2 the command could not start (invalid prompt set, invalid or empty
case set, configuration not usable). A failing metric does not make the command fail: the report
says it.
"""

import argparse
import logging
import sys
from pathlib import Path

from app.config import ConfigurationError, load_settings
from app.profile_definition import load_profile_definition
from app.prompts import load_prompt_set
from app.providers import ProvidersNotReady
from app.redaction import RedactionGate
from eval.backends import Backend, fake_backend, live_backend
from eval.cases import ROOT, CaseSetError, load_case_set
from eval.run import run_evaluation, write_report

DEFAULT_OUT = ROOT / "eval" / "reports"
DEFAULT_RATINGS = ROOT / "eval" / "ratings.csv"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval", description=__doc__)
    parser.add_argument("--config", default="", help="approved configuration id, or 'fake'")
    parser.add_argument("--prompts", default="", help="prompt set file (default: the active one)")
    parser.add_argument("--ratings", default="", help="reviewer rating file (CSV)")
    parser.add_argument("--out", default="", help="report directory (default: eval/reports)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        settings = load_settings()
        prompt_path = args.prompts or settings.prompt_set_file
        prompts = load_prompt_set(Path(prompt_path) if prompt_path else None)
        cases = load_case_set()
        definition = load_profile_definition(
            Path(settings.profile_definition_file) if settings.profile_definition_file else None
        )
        backend: Backend = fake_backend() if args.config == "fake" else live_backend(args.config)
    except (ConfigurationError, CaseSetError, ProvidersNotReady) as error:
        print(f"eval: {error}", file=sys.stderr)
        return 2
    ratings = Path(args.ratings) if args.ratings else DEFAULT_RATINGS
    gate = RedactionGate(lambda: ())
    report = run_evaluation(cases, backend, prompts, gate, definition, ratings)
    markdown, js = write_report(report, Path(args.out) if args.out else DEFAULT_OUT)
    print((markdown).read_text(encoding="utf-8"))
    print(f"Report: {markdown}\nReport: {js}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

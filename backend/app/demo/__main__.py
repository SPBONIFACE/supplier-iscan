"""The administrator command that builds the public demo (#50).

    python -m app.demo load --organisation <demo organisation id>

It copies the finished runs of the configured demo organisation (`DEMO_ORGANISATION_ID`) into
read-only demo profiles, names stripped, replacing the earlier set. The organisation id must be the
configured one: any other is refused. No model is called and nothing is crawled.
"""

import argparse
import logging
import sys
import uuid

from app.config import ConfigurationError, load_settings
from app.db import Database
from app.demo.build import DemoOrganisationRefused, load_demo_profiles
from app.main import load_definition


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m app.demo", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser(
        "load", help="replace the demo set with the demo organisation's runs"
    )
    load.add_argument("--organisation", required=True, type=uuid.UUID)
    arguments = parser.parse_args(argv)

    try:
        settings = load_settings()
        if not settings.database_url:
            print("DATABASE_URL is not set", file=sys.stderr)
            return 2
        database = Database(settings.database_url)
        definition = load_definition(settings)
        with database.session() as db:
            copied = load_demo_profiles(db, settings, definition, arguments.organisation)
    except (DemoOrganisationRefused, ConfigurationError) as refused:
        print(str(refused), file=sys.stderr)
        return 1
    print(
        f"Demo set replaced: {copied.profiles} profile(s); "
        f"{copied.skipped_natural_person} natural-person business(es) not copied."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

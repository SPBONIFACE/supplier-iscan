"""Startup: write the provider configuration file into `provider_configs`.

Each configuration of the file is inserted or updated. A row whose id is no longer in the file is
kept (usage records refer to it) but disabled. Only the fields of the configuration are written;
there is no key column.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utc_now
from app.models import ProviderConfig
from app.providers.catalogue import ProviderCatalogue

logger = logging.getLogger(__name__)

_FIELDS = (
    "provider",
    "api",
    "model_id",
    "endpoint",
    "training_setting",
    "retention",
    "region",
    "transfer_mechanism",
    "verified_at",
    "enabled",
)


def sync_provider_configs(db: Session, catalogue: ProviderCatalogue) -> None:
    rows = {row.id: row for row in db.scalars(select(ProviderConfig)).all()}
    now = utc_now()
    for config in catalogue.provider_configs:
        values = {name: getattr(config, name) for name in _FIELDS}
        row = rows.pop(config.id, None)
        if row is None:
            db.add(ProviderConfig(id=config.id, updated_at=now, **values))
            continue
        if any(getattr(row, name) != value for name, value in values.items()):
            for name, value in values.items():
                setattr(row, name, value)
            row.updated_at = now
    for row in rows.values():
        if row.enabled:
            row.enabled = False
            row.updated_at = now
            logger.info("Provider configuration %r is no longer in the file: disabled", row.id)
    db.commit()

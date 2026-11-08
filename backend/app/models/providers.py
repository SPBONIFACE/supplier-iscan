"""Approved provider configurations (spec F6, Data model: ProviderConfig).

The rows mirror the provider configuration file (`app.providers.catalogue`), written at startup,
so that usage records (#12) and the administrator's choice per role (#49) can refer to them. A
configuration removed from the file is kept, disabled, because past usage records refer to it.
There is no key column: API keys are never written to the database.
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

PROVIDERS = ("anthropic", "google", "openai", "mistral", "perplexity")


class ProviderConfig(Base):
    __tablename__ = "provider_configs"
    __table_args__ = (
        CheckConstraint(
            "provider IN (" + ", ".join(repr(name) for name in PROVIDERS) + ")", name="provider"
        ),
    )

    # The id written in the configuration file, e.g. "gemini-flash-structuring".
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))
    api: Mapped[str] = mapped_column(String(200))
    model_id: Mapped[str] = mapped_column(String(200))
    endpoint: Mapped[str] = mapped_column(String(500))
    training_setting: Mapped[str] = mapped_column(String(200))
    retention: Mapped[str] = mapped_column(String(200))
    region: Mapped[str] = mapped_column(String(200))
    transfer_mechanism: Mapped[str] = mapped_column(String(200))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

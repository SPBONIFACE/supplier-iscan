"""FastAPI dependency giving an endpoint the application's settings.

def endpoint(settings: CurrentSettings) -> ...:
"""

from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


CurrentSettings = Annotated[Settings, Depends(get_settings)]

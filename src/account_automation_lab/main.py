from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from account_automation_lab.api import create_app
from account_automation_lab.settings import get_settings
from account_automation_lab.ui.pages import mount_ui


def build_app() -> FastAPI:
    settings = get_settings()
    app = create_app(settings=settings)
    mount_ui(app)
    try:
        from nicegui import ui

        ui.run_with(app)
    except ImportError:
        pass
    return app


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "account_automation_lab.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


app = build_app()

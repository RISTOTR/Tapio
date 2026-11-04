"""Disposable browser-test server; only uses an isolated migrated test schema."""

import json
import os

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tapio.confirmation import api
from tapio.confirmation.service import ConfirmationService

factory = sessionmaker(create_engine(os.environ["BROWSER_TEST_DATABASE_URL"]))
service = ConfirmationService(
    factory, json.loads(os.environ["BROWSER_TEST_BATCH"]), enabled=lambda: True
)
api.service = lambda: service
app = FastAPI()
app.include_router(api.router)


@app.get("/baseline")
def baseline():
    from pathlib import Path

    from fastapi.responses import HTMLResponse

    return HTMLResponse(Path(os.environ["BROWSER_BASELINE_HTML"]).read_text())

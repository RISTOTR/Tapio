"""Fail-closed accepted configuration and database-enforced read-only sessions."""

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from apps.api.app.core.config import get_settings
from apps.api.app.domain.models import Document
from data_pipeline.labels.snapshot import fingerprint

CONFIG = Path("data/interim/phase09i/phase09h_configuration.json")
CONFIG_HASH = "3b3e0d809c205ca37f7c39414aca407fe01a58a15935d1a3db93d2ae2d97988b"
MODEL = "gpt-5.4-mini-2026-03-17"
SETTINGS = {
    "max_rounds": 6,
    "max_completion_tokens": 3000,
    "reasoning_effort": "none",
    "parallel_tool_calls": False,
    "store": False,
}
HISTORY = Path("data/interim/pilot")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_mode():
    if os.getenv("TAPIO_PILOT_MODE", "").lower() != "true":
        raise ValueError("PILOT_MODE_DISABLED")


def load_config():
    require_mode()
    if digest(CONFIG) != CONFIG_HASH:
        raise ValueError("PILOT_CONFIGURATION_CHANGED")
    config = json.loads(CONFIG.read_text())
    if (
        config["identifier"] != "PHASE09H_EXCLUSIVE_C_V1"
        or config["model"] != MODEL
        or config["settings"] != SETTINGS
    ):
        raise ValueError("PILOT_CONFIGURATION_CHANGED")
    for path, expected in config["implementation_hashes"].items():
        if digest(path) != expected:
            raise ValueError("ACCEPTED_CORE_CHANGED")
    if digest(config["data_snapshot_path"]) != config["data_snapshot_hash"]:
        raise ValueError("SOURCE_SNAPSHOT_CHANGED")
    snapshot = json.loads(Path(config["data_snapshot_path"]).read_text())
    for path, expected in {**snapshot["protected_files"], **snapshot["protocol_hashes"]}.items():
        if digest(path) != expected:
            raise ValueError("ACCEPTED_EVIDENCE_CHANGED")
    energy = json.loads(Path("data/interim/phase06/protected_energy.json").read_text())
    if any(digest(path) != expected for path, expected in energy.items()):
        raise ValueError("ACCEPTED_ELECTRICITY_CHANGED")
    return config, snapshot


def readonly_engine(url=None):
    url = url or str(get_settings().database_url)
    if not url.startswith("postgresql"):
        raise ValueError("POSTGRESQL_READ_ONLY_REQUIRED")
    return create_engine(
        url, pool_pre_ping=True, connect_args={"options": "-c default_transaction_read_only=on"}
    )


@contextmanager
def readonly_session(engine):
    with Session(engine) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        session.execute(text("SET LOCAL statement_timeout = '20000ms'"))
        try:
            yield session
        finally:
            session.rollback()


def source_fingerprints(engine, config):
    with readonly_session(engine) as session:
        actual = {
            name: fingerprint(
                [
                    dict(row)
                    for row in session.execute(select(Document.metadata.tables[name])).mappings()
                ]
            )
            for name in config["source_fingerprints"]
        }
    if actual != config["source_fingerprints"]:
        raise ValueError("SOURCE_SNAPSHOT_CHANGED")
    return actual

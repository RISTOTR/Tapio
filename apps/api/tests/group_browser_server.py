"""Browser harness restricted to an explicitly supplied disposable schema and plan."""

import os
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tapio.confirmation import api
from tapio.confirmation.groups import GroupReview
from tapio.confirmation.persistent import PersistentQueue

url = os.environ["BROWSER_TEST_DATABASE_URL"]
if "energy_test_" not in url:
    raise ValueError("DISPOSABLE_SCHEMA_REQUIRED")
q = PersistentQueue(sessionmaker(create_engine(url)), Path(os.environ["GROUP_TEST_ROOT"]))
q.enabled = lambda: True
g = GroupReview(q)
g.verify_sources = lambda: {}
api.group_review = lambda: g
api.persistent_queue = lambda: q
app = FastAPI()
app.include_router(api.router)

"""Real HTTP and production import code, restricted to an isolated test schema."""

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.tests.workspace_browser_server import app as app
from data_pipeline.labels.snapshot import fingerprint
from tapio.confirmation import api as review_api
from tapio.confirmation.groups import GroupReview
from tapio.confirmation.persistent import PersistentQueue
from tapio.importing import api as import_api
from tapio.importing.service import ImportWorkflow

url = os.environ["BROWSER_TEST_DATABASE_URL"]
if "energy_test_" not in url:
    raise ValueError("DISPOSABLE_SCHEMA_REQUIRED")
q = PersistentQueue(sessionmaker(create_engine(url)), Path(os.environ["IMPORT_TEST_ROOT"]))
q.enabled = lambda: True
w = ImportWorkflow(q)


def verify(group):
    expected = q.manifest()["source_fingerprints"]
    tables = w.read_tables()
    actual = {n: fingerprint(tables[n]) for n in expected}
    if actual != expected:
        raise ValueError("TEST_SOURCE_CHANGED")
    return actual


GroupReview.verify_sources = verify
review_api.persistent_queue = lambda: q
review_api.group_review = lambda: GroupReview(q)
# Keep plans across the actual group preview/apply routes.
group = GroupReview(q)
review_api.group_review = lambda: group
import_api.workflow = lambda: w

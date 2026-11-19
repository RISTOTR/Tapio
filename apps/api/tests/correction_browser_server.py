"""Correction UI fixture on the existing isolated import test database."""

from apps.api.tests.import_browser_server import app as app
from apps.api.tests.import_browser_server import q
from tapio.pilot import corrections

instance = corrections.Corrections(q)
corrections.corrections = lambda: instance

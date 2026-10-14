"""Synthetic subprocess server for genuine stdio protocol tests, no OAuth/network."""

from apps.api.tests.gmail_fixtures import FakeGmail
from integrations.gmail.auth import GmailSettings
from integrations.gmail.client import GmailClient
from integrations.gmail.server import create_server

if __name__ == "__main__":
    client = GmailClient(FakeGmail(), GmailSettings())
    create_server(lambda: client).run(transport="stdio")

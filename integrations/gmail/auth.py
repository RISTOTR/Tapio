"""Installed-app OAuth with exact grant verification; no implicit browser authorization."""

import json
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from tapio.tools.errors import ErrorCode, ToolFailure

from .cache import private_write

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SCOPES = (SCOPE,)


class GmailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TAPIO_GMAIL_", env_file=".env", extra="ignore")
    client_secret: Path = Path(".private/gmail/client_secret.json")
    token: Path = Path(".private/gmail/token.json")
    cache: Path = Path("data/interim/gmail/cache")
    evidence: Path = Path("data/interim/gmail/evidence")


def check_scopes(scopes):
    actual = set(scopes.split() if isinstance(scopes, str) else (scopes or []))
    if actual != set(SCOPES):
        raise ToolFailure(ErrorCode.SCOPE_REJECTED)
    return actual


def credentials(settings=None, authorize=False):
    import requests
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    settings = settings or GmailSettings()
    creds = None
    try:
        if settings.token.exists():
            saved = json.loads(settings.token.read_text())
            check_scopes(saved.get("scopes"))
            creds = Credentials.from_authorized_user_info(saved)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        if not creds or not creds.valid:
            if not authorize or not settings.client_secret.is_file():
                raise ToolFailure(ErrorCode.AUTHENTICATION_REQUIRED)
            config = json.loads(settings.client_secret.read_text())
            if "installed" not in config:
                raise ToolFailure(ErrorCode.AUTHENTICATION_REQUIRED)
            flow = InstalledAppFlow.from_client_config(config, SCOPES)
            creds = flow.run_local_server(
                host="127.0.0.1",
                port=0,
                open_browser=True,
                authorization_prompt_message=(
                    "Complete Gmail read-only consent in the opened browser."
                ),
                timeout_seconds=180,
                access_type="offline",
                prompt="consent",
                include_granted_scopes="false",
            )
            check_scopes(creds.granted_scopes or creds.scopes)
        # Inspect the actual access token's grant, not just the locally requested scopes.
        response = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"access_token": creds.token},
            timeout=20,
        )
        response.raise_for_status()
        check_scopes(response.json().get("scope"))
        private_write(settings.token, creds.to_json().encode())
        return creds
    except ToolFailure:
        raise
    except Exception as exc:
        raise ToolFailure(ErrorCode.AUTHENTICATION_REQUIRED) from exc


def main():
    import argparse

    p = argparse.ArgumentParser(
        description="Authorize Gmail locally; exact gmail.readonly grant only."
    )
    p.add_argument("--authorize", action="store_true")
    args = p.parse_args()
    try:
        credentials(authorize=args.authorize)
        print(json.dumps({"status": "AUTHORIZED", "verified_scopes": list(SCOPES)}))
    except ToolFailure as exc:
        print(json.dumps({"status": "ERROR", "code": exc.code}))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()

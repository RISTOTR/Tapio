"""Human-only evidence acceptance. Not registered in MCP or the agent tool registry."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from apps.api.app.domain.models import Document
from data_pipeline.ingest.documents.loader import import_document
from tapio.tools.errors import ErrorCode, ToolFailure
from tapio.tools.schemas import Schema

from .cache import private_write
from .models import Download, Message


class EmailEvidence(Schema):
    provider: str = "GMAIL"
    external_message_id: str
    thread_id: str
    sender: str
    subject: str
    message_date: str
    retrieved_at: datetime
    content_hash: str
    body: str
    body_truncated: bool
    links: list[str]
    accepted_at: datetime
    attachment_id: str | None = None
    download_hash: str | None = None
    source_document_id: UUID | None = None
    document_sha256: str | None = None
    import_status: str = "BODY_EVIDENCE"
    error_code: str | None = None
    source_classification: str | None = None
    accepted_fields: dict[str, str] = {}
    body_is_selected_excerpt: bool = False


def accept_evidence(
    message,
    settings,
    *,
    human_confirmed=False,
    download=None,
    session_factory=None,
    selected_excerpts=None,
    accepted_fields=None,
    source_classification=None,
):
    if not human_confirmed:
        raise ToolFailure(ErrorCode.HUMAN_APPROVAL_REQUIRED)
    message = Message.model_validate(message)
    selection = ""
    if selected_excerpts is not None:
        if not selected_excerpts or any(not x or x not in message.body for x in selected_excerpts):
            raise ValueError("excerpt_must_be_literal_source_text")
        selection = json.dumps(
            [selected_excerpts, accepted_fields or {}, source_classification], sort_keys=True
        )
    elif accepted_fields or source_classification:
        raise ValueError("classified_evidence_requires_selected_excerpts")
    key = hashlib.sha256(
        (
            message.message_id
            + ":"
            + (download.attachment_id if download else "body")
            + ":"
            + message.content_hash
            + selection
        ).encode()
    ).hexdigest()
    path = settings.evidence / (key + ".json")
    record = EmailEvidence(
        external_message_id=message.message_id,
        thread_id=message.thread_id,
        sender=message.sender,
        subject=message.subject,
        message_date=message.message_date,
        retrieved_at=message.retrieved_at,
        content_hash=message.content_hash,
        body="\n\n".join(selected_excerpts) if selected_excerpts is not None else message.body,
        body_truncated=message.body_truncated,
        links=[] if selected_excerpts is not None else message.links,
        accepted_at=datetime.now(UTC),
        source_classification=source_classification,
        accepted_fields=accepted_fields or {},
        body_is_selected_excerpt=selected_excerpts is not None,
    )
    if download is None:
        if message.body_truncated:
            raise ToolFailure(ErrorCode.OUTPUT_LIMIT)
        if path.exists():
            return EmailEvidence.model_validate_json(path.read_text())
        private_write(path, record.model_dump_json(indent=2).encode())
        return record
    download = Download.model_validate(download)
    if download.message_id != message.message_id or download.attachment_id not in {
        a.attachment_id for a in message.attachments
    }:
        raise ToolFailure(ErrorCode.ATTACHMENT_MISSING)
    raw = (settings.cache / "attachments" / (download.sha256 + ".pdf")).read_bytes()
    if hashlib.sha256(raw).hexdigest() != download.sha256:
        raise ToolFailure(ErrorCode.ATTACHMENT_MISSING)
    if session_factory is None:
        raise ValueError("explicit_human_import_session_required")
    # Durable intent before the existing atomic DB loader. Retrying after a crash
    # reuses its SHA-256 idempotency, then completes the provenance manifest.
    record = record.model_copy(
        update={
            "attachment_id": download.attachment_id,
            "download_hash": download.sha256,
            "import_status": "PENDING_IMPORT",
        }
    )
    private_write(path, record.model_dump_json(indent=2).encode())
    result = import_document(raw, filename=download.filename, session_factory=session_factory)
    updates = {"import_status": result["status"], "error_code": result.get("error_code")}
    if result["status"] in ("imported", "already_imported"):
        with session_factory() as s:
            document = s.scalar(select(Document).where(Document.sha256 == download.sha256))
            if document is None:
                raise ToolFailure(ErrorCode.INTERNAL_ERROR)
            updates.update(source_document_id=document.id, document_sha256=document.sha256)
    record = record.model_copy(update=updates)
    private_write(path, record.model_dump_json(indent=2).encode())
    return record


def main():
    import argparse

    from apps.api.app.core.database import SessionLocal

    from .auth import GmailSettings
    from .client import GmailClient

    p = argparse.ArgumentParser(
        description="Human-selected email evidence acceptance; never bulk import."
    )
    p.add_argument("--message-id", required=True)
    p.add_argument("--attachment-id")
    p.add_argument("--confirm-selected-evidence", action="store_true")
    args = p.parse_args()
    if not args.confirm_selected_evidence:
        raise SystemExit("HUMAN_APPROVAL_REQUIRED")
    client = GmailClient.connected()
    message = client.get_message(args.message_id)
    download = (
        client.download_attachment(args.message_id, args.attachment_id)
        if args.attachment_id
        else None
    )
    record = accept_evidence(
        message,
        GmailSettings(),
        human_confirmed=True,
        download=download,
        session_factory=SessionLocal,
    )
    print(
        json.dumps(
            {
                "status": record.import_status,
                "source_document_id": str(record.source_document_id)
                if record.source_document_id
                else None,
                "error_code": record.error_code,
            }
        )
    )


if __name__ == "__main__":
    main()

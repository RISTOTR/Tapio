"""Read-only official Gmail API adapter, independently usable without MCP."""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tapio.tools.errors import ErrorCode, ToolFailure

from .auth import GmailSettings, credentials
from .cache import Cache, private_write
from .mime import metadata, normalize
from .models import (
    AttachmentID,
    AttachmentsResult,
    Download,
    LinksResult,
    Message,
    MessageID,
    MessageMetadata,
    SearchResult,
    ThreadID,
    ThreadResult,
    require_query,
)

MAX_ATTACHMENT = 10 * 1024 * 1024


class GmailClient:
    def __init__(self, service, settings=None):
        self.service = service
        self.settings = settings or GmailSettings()
        self.cache = Cache(self.settings.cache)

    @classmethod
    def connected(cls):
        import httplib2
        from google_auth_httplib2 import AuthorizedHttp
        from googleapiclient.discovery import build

        settings = GmailSettings()
        http = AuthorizedHttp(credentials(settings), http=httplib2.Http(timeout=20))
        return cls(build("gmail", "v1", http=http, cache_discovery=False), settings)

    @staticmethod
    def execute(request):
        try:
            return request.execute(num_retries=1)
        except Exception as exc:
            raise ToolFailure(ErrorCode.GMAIL_API_FAILURE) from exc

    def get_metadata(self, message_id):
        MessageID(message_id=message_id)
        cached = self.cache.read("metadata-" + message_id)
        if cached and datetime.now(UTC) - datetime.fromisoformat(
            cached["retrieved_at"]
        ) < timedelta(hours=24):
            return MessageMetadata.model_validate(cached)
        raw = self.execute(
            self.service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
        )
        value = metadata(raw)
        self.cache.write("metadata-" + message_id, value.model_dump(mode="json"))
        return value

    def search_messages(self, query, max_results=10):
        args = require_query(query, max_results)
        raw = self.execute(
            self.service.users()
            .messages()
            .list(userId="me", q=args.query, maxResults=args.max_results, includeSpamTrash=False)
        )
        items = [self.get_metadata(m["id"]) for m in raw.get("messages", [])[: args.max_results]]
        return SearchResult(
            items=items,
            more_available=bool(raw.get("nextPageToken"))
            or len(raw.get("messages", [])) > args.max_results,
            status="OK" if items else "NO_MATCHING_MESSAGES",
        )

    def get_message(self, message_id, refresh=False):
        MessageID(message_id=message_id, refresh=refresh)
        pointer = self.cache.read("message-" + message_id)
        if pointer and not refresh:
            cached = self.cache.read(pointer["key"])
            if cached and datetime.now(UTC) - datetime.fromisoformat(
                cached["retrieved_at"]
            ) < timedelta(hours=24):
                return Message.model_validate(cached)
        raw = self.execute(
            self.service.users().messages().get(userId="me", id=message_id, format="full")
        )
        result = normalize(raw)
        key = (
            "version-"
            + hashlib.sha256(
                (message_id + ":" + result.history_id + ":" + result.content_hash).encode()
            ).hexdigest()
        )
        self.cache.write(key, result.model_dump(mode="json"))
        self.cache.write("message-" + message_id, {"key": key})

        # Inline attachment data is retained only for an explicitly retrieved message,
        # within the PDF size bound, outside the model-facing message object.
        def inline(part):
            body = part.get("body", {})
            if (
                part.get("filename")
                and body.get("data")
                and not body.get("attachmentId")
                and len(body["data"]) <= MAX_ATTACHMENT * 2
            ):
                aid = "inline_" + part.get("partId", "0").replace(".", "_")
                self.cache.write("inline-" + message_id + "-" + aid, {"data": body["data"]})
            for child in part.get("parts", []):
                inline(child)

        inline(raw.get("payload", {}))
        return result

    def get_thread(self, thread_id, max_results=10):
        ThreadID(thread_id=thread_id, max_results=max_results)
        raw = self.execute(
            self.service.users()
            .threads()
            .get(
                userId="me",
                id=thread_id,
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
        )
        values = raw.get("messages", [])
        return ThreadResult(
            items=[metadata(r) for r in values[:max_results]], truncated=len(values) > max_results
        )

    def list_attachments(self, message_id):
        return AttachmentsResult(items=self.get_message(message_id).attachments)

    def list_links(self, message_id):
        return LinksResult(items=self.get_message(message_id).links)

    def download_attachment(self, message_id, attachment_id):
        AttachmentID(message_id=message_id, attachment_id=attachment_id)
        items = self.get_message(message_id).attachments
        attachment = next((a for a in items if a.attachment_id == attachment_id), None)
        if attachment is None:
            raise ToolFailure(ErrorCode.ATTACHMENT_MISSING)
        if attachment.mime_type != "application/pdf":
            raise ToolFailure(ErrorCode.UNSUPPORTED_MIME_TYPE)
        if attachment.size > MAX_ATTACHMENT:
            raise ToolFailure(ErrorCode.OUTPUT_LIMIT)
        key = "download-" + hashlib.sha256((message_id + ":" + attachment_id).encode()).hexdigest()
        cached = self.cache.read(key)
        if cached:
            result = Download.model_validate(cached)
            path = self.settings.cache / "attachments" / (result.sha256 + ".pdf")
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == result.sha256:
                return result
        if attachment_id.startswith("inline_"):
            raw = self.cache.read("inline-" + message_id + "-" + attachment_id)
            if raw is None:
                raise ToolFailure(ErrorCode.ATTACHMENT_MISSING)
        else:
            raw = self.execute(
                self.service.users()
                .messages()
                .attachments()
                .get(userId="me", messageId=message_id, id=attachment_id)
            )
        value = raw.get("data", "")
        if len(value) > MAX_ATTACHMENT * 2:
            raise ToolFailure(ErrorCode.OUTPUT_LIMIT)
        # Attachment size bound differs from the text MIME limit.
        import base64

        try:
            data = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        except Exception as exc:
            raise ToolFailure(ErrorCode.GMAIL_API_FAILURE) from exc
        if len(data) > MAX_ATTACHMENT:
            raise ToolFailure(ErrorCode.OUTPUT_LIMIT)
        if not data.startswith(b"%PDF-"):
            raise ToolFailure(ErrorCode.UNSUPPORTED_MIME_TYPE)
        digest = hashlib.sha256(data).hexdigest()
        private_write(self.settings.cache / "attachments" / (digest + ".pdf"), data)
        result = Download(
            message_id=message_id,
            attachment_id=attachment_id,
            filename=Path(attachment.filename).name,
            mime_type="application/pdf",
            sha256=digest,
            size=len(data),
            handle=digest,
        )
        self.cache.write(key, result.model_dump(mode="json"))
        return result

"""Bounded MIME extraction. HTML is parsed as text, never rendered or fetched."""

import base64
import hashlib
import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

from tapio.tools.errors import ErrorCode, ToolFailure

from .models import Attachment, Message, MessageMetadata


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.links = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1
        if tag in ("p", "div", "br", "li"):
            self.text.append("\n")
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.links.append(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def decode(value):
    if len(value) > 3_000_000:
        raise ToolFailure(ErrorCode.OUTPUT_LIMIT)
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise ToolFailure(ErrorCode.GMAIL_API_FAILURE) from exc


def metadata(raw):
    headers = {
        h["name"].lower(): h.get("value", "") for h in raw.get("payload", {}).get("headers", [])
    }
    return MessageMetadata(
        message_id=raw["id"],
        thread_id=raw["threadId"],
        sender=headers.get("from", "")[:512],
        subject=headers.get("subject", "")[:512],
        message_date=headers.get("date", "")[:100],
        retrieved_at=datetime.now(UTC),
        history_id=str(raw.get("historyId", ""))[:100],
    )


def normalize(raw):
    meta = metadata(raw)
    plain = []
    html = []
    attachments = []
    links = []
    nodes = 0

    def walk(part, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 12 or nodes > 100:
            raise ToolFailure(ErrorCode.OUTPUT_LIMIT)
        body = part.get("body", {})
        filename = part.get("filename", "")
        mime = part.get("mimeType", "")
        if filename:
            # Inline attachments have no attachmentId; partId is explicitly distinguished.
            aid = body.get("attachmentId") or "inline_" + part.get("partId", "0").replace(".", "_")
            attachments.append(
                Attachment(
                    message_id=meta.message_id,
                    attachment_id=aid,
                    filename=filename[:255],
                    mime_type=mime[:100],
                    size=max(0, int(body.get("size", 0))),
                )
            )
        elif mime in ("text/plain", "text/html") and body.get("data"):
            value = decode(body["data"]).decode("utf-8", errors="replace")
            if mime == "text/plain":
                plain.append(value)
            else:
                parser = TextHTML()
                parser.feed(value)
                html.append("".join(parser.text))
                links.extend(parser.links)
        for child in part.get("parts", []):
            walk(child, depth + 1)

    walk(raw.get("payload", {}))
    text = "\n".join(plain or html)
    links.extend(re.findall(r'https?://[^\s<>"\x27]+', text))
    safe = []
    for link in links:
        link = link.rstrip(".,);")
        try:
            u = urlsplit(link)
        except ValueError:
            continue
        if (
            u.scheme in ("http", "https")
            and u.hostname
            and not u.username
            and len(link) <= 2048
            and link not in safe
        ):
            safe.append(link)
    if len(attachments) > 30:
        raise ToolFailure(ErrorCode.OUTPUT_LIMIT)
    return Message(
        **meta.model_dump(),
        body=text[:16000],
        body_truncated=len(text) > 16000,
        attachments=attachments,
        links=safe[:50],
        content_hash=hashlib.sha256(
            json.dumps(
                {
                    "body": text,
                    "links": safe[:50],
                    "attachments": [a.model_dump(mode="json") for a in attachments],
                    "sender": meta.sender,
                    "subject": meta.subject,
                    "message_date": meta.message_date,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest(),
    )

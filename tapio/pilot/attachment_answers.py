"""Explicit selected-email PDF analysis. Private cache only; no import or acceptance."""

import asyncio
import hashlib
import io

from pypdf import PdfReader

from data_pipeline.documents.base import DocumentError
from data_pipeline.documents.detect import parser_for
from data_pipeline.ingest.documents import extract
from integrations.gmail.auth import GmailSettings
from integrations.gmail.models import Download, MessageID
from tapio.pilot.evidence_routing import gmail_lookup, gmail_query, needs_gmail_auth
from tapio.pilot.invoice_comparison import document_identity, final_bill_facts
from tapio.tools.gmail import gmail_session, register_gmail
from tapio.tools.registry import Registry

MAX_PDFS = 6


def analyze_download(value):
    download = Download.model_validate(value)
    if download.handle != download.sha256 or download.size > 10 * 1024 * 1024:
        raise ValueError("ATTACHMENT_INTEGRITY")
    path = GmailSettings().cache / "attachments" / (download.handle + ".pdf")
    if path.is_symlink():
        raise ValueError("ATTACHMENT_INTEGRITY")
    raw = path.read_bytes()
    if len(raw) != download.size or hashlib.sha256(raw).hexdigest() != download.sha256:
        raise ValueError("ATTACHMENT_INTEGRITY")
    if len(PdfReader(io.BytesIO(raw)).pages) > 40:
        raise ValueError("ATTACHMENT_PAGE_LIMIT")
    pages = extract(raw)
    provenance = {
        "source": "Email PDF attachment",
        "filename": download.filename,
        "reference": download.message_id,
        "attachment_id": download.attachment_id,
        "sha256": download.sha256,
        "page_count": len(pages),
    }
    try:
        parsed = parser_for(pages).parse(pages)
    except (DocumentError, ValueError):
        facts = final_bill_facts(pages)
        if facts:
            return [{**provenance, **facts, **document_identity(pages)}], [
                f"{download.filename}: final bill {facts['total_eur']} EUR; printed totals checked."
            ]
        text = "\n\n".join(f"Page {n}:\n{p}" for n, p in enumerate(pages, 1))
        return [
            {
                **provenance,
                "subject": download.filename,
                "authority": "Extracted text — numeric fields not validated",
                "excerpt": text[:12000],
                "excerpt_limited": len(text) > 12000,
            }
        ], [
            f"{download.filename}: text extracted, but invoice amounts could not be validated "
            "for this layout. Images or rotated text may be missing from extraction."
        ]
    record = {
        **provenance,
        **document_identity(pages),
        "subject": download.filename,
        "vendor": parsed.vendor,
        "date": str(parsed.document_date),
        "parser_version": parsed.parser_version,
        "authority": "Parsed source facts — not imported or tax-approved",
    }
    lines = []
    if parsed.bill:
        bill = parsed.bill
        record.update(
            customer=bill.customer,
            due_date=str(bill.due_date),
            invoice_type="Invoice",
            invoice_number=bill.invoice_number,
            payment_reference=bill.reference,
            total_eur=str(bill.total_eur),
            vat_eur=str(bill.vat_eur),
            subtotal_eur=str(bill.subtotal_eur),
            currency="EUR",
            energy=[e.model_dump(mode="json") for e in bill.energy],
        )
        lines.append(
            f"{bill.vendor} · {bill.invoice_date}: invoice {bill.total_eur:.2f} EUR, "
            f"including {bill.vat_eur:.2f} EUR printed VAT."
        )
        for energy in bill.energy:
            if energy.solar_export_kwh is not None:
                lines.append(
                    f"{energy.period_start}–{energy.period_end}: "
                    f"{energy.solar_export_kwh} kWh exported to the grid (page {energy.page})."
                )
    else:
        record["parsed_facts"] = parsed.model_dump(mode="json")
    return [record], lines


async def analyze_attachments(pilot, question, selected):
    from tapio.pilot.workspace_answers import response, session

    current = session()
    directory = pilot.history.directory(current.id)
    records, lines, limits = [], [], []
    inspected = 0
    try:
        if not selected:
            search = gmail_query(question, [])
            if not search:
                return response(
                    "Name the email sender and month/year, or first find the emails "
                    "and then ask to analyze their attachments."
                )
            selected, limited = await gmail_lookup(search, directory)
            if limited:
                limits.append("Selected results only; narrow the period for more emails.")
        # Selection comes only from server-saved evidence or the bounded Gmail lookup.
        ids = list(
            dict.fromkeys(
                MessageID(message_id=r["reference"]).message_id
                for r in selected
                if r.get("reference")
            )
        )
        if len(ids) > 3:
            limits.append("At most three messages checked. Narrow the selection for more.")
        async with asyncio.timeout(150), gmail_session() as connected:
            registry = Registry(audit_path=directory / "attachment-tools.jsonl")
            register_gmail(registry, connected)

            async def call(name, args):
                result = await registry.call(name, args)
                if not result["ok"]:
                    raise ValueError(result["error"]["code"])
                return result["data"]

            for message_id in ids[:3]:
                attachments = (await call("gmail_list_attachments", {"message_id": message_id}))[
                    "items"
                ]
                if not attachments:
                    limits.append(
                        "A selected email has no attachments. Linked documents were not followed."
                    )
                for attachment in attachments:
                    if attachment["mime_type"] != "application/pdf":
                        limits.append(
                            f"{attachment['filename']}: only PDF attachments are supported."
                        )
                        continue
                    if inspected >= MAX_PDFS:
                        limits.append(
                            "Stopped at six PDFs. Narrow the selected emails to analyze more."
                        )
                        break
                    inspected += 1
                    try:
                        downloaded = await call(
                            "gmail_download_attachment",
                            {
                                "message_id": message_id,
                                "attachment_id": attachment["attachment_id"],
                            },
                        )
                        if (
                            downloaded["message_id"] != message_id
                            or downloaded["attachment_id"] != attachment["attachment_id"]
                        ):
                            raise ValueError("ATTACHMENT_IDENTITY_MISMATCH")
                        found, facts = await asyncio.to_thread(analyze_download, downloaded)
                        records.extend(found)
                        lines.extend(facts)
                    except Exception as exc:
                        if needs_gmail_auth(exc):
                            raise
                        limits.append(
                            f"{attachment['filename']}: could not validate or extract this PDF. "
                            "It may require a text version or a supported invoice layout."
                        )
    except Exception as exc:
        limits.append(
            "Reconnect Gmail read-only authorization and retry."
            if needs_gmail_auth(exc)
            else "Attachment retrieval did not complete. Available results may be partial."
        )
    result = response(
        f"Analyzed {len(records)} PDF attachments from the selected emails."
        if records
        else "No PDF attachment could be analyzed. See the retrieval details below.",
        records=records,
        breakdown=lines,
        sources=[
            {
                "label": "Gmail attachments",
                "status": "used" if records else "unavailable",
                "detail": "Selected PDFs cached locally; no database import.",
            }
        ],
        limits=list(
            dict.fromkeys(
                limits
                + [
                    "Printed VAT is not a deduction decision. "
                    "Source records and labels are unchanged.",
                    "Solar export measures delivery to the grid, not total panel production.",
                ]
            )
        ),
    )
    return result.model_copy(update={"session": current})

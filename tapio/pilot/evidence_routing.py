"""Bounded workspace evidence routing around the unchanged financial pilot.

Email bodies are data, never instructions. This layer cannot calculate financial
answers, accept evidence, download attachments, or change Gmail/source records.
"""

import asyncio
import re
import time
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from uuid import uuid4

from apps.api.app.services.tool_queries import Queries
from integrations.gmail.auth import GmailSettings
from integrations.gmail.evidence import EmailEvidence
from integrations.gmail.models import MessageID, Search
from tapio.knowledge.models import Kind
from tapio.knowledge.queries import KnowledgeQueries
from tapio.knowledge.store import load_bundle
from tapio.pilot.config import readonly_engine, readonly_session
from tapio.pilot.contracts import Coverage, PilotResponse, Session
from tapio.pilot.transaction_search import requested_dates
from tapio.tools.gmail import gmail_session, register_gmail
from tapio.tools.registry import Registry
from tapio.tools.schemas import DocumentQuery

EVIDENCE = re.compile(
    r"\b(email|gmail|message|receipt|invoice|contract|agreement|sopimus|lasku|kuitti)\w*\b", re.I
)
CALCULATION = re.compile(
    r"\b(total|sum|how much|expenses|income|costs|compare|average|calculate)\b", re.I
)
PURPOSE = re.compile(r"\b(paytrail|payment purpose|recipient)\b", re.I)
STOP = set(
    (
        "when does did my the a an in on of for from to i have do is any find "
        "show me what which end ends start starts date dates contract "
        "electricity invoice invoices receipt receipts email gmail message "
        "messages agreement payment purpose after before since"
    ).split()
)


def terms(question):
    return [
        w
        for w in re.findall(r"[\w@.-]+", question.casefold())
        if len(w) > 2 and w not in STOP and not w.isdigit()
    ][:12]


def subject(question):
    explicit = re.search(r"from[:\s]+([\w@.-]+)", question, re.I)
    if explicit and not explicit[1].isdigit():
        return explicit[1].rstrip(".?")
    words = [w for w in terms(question) if w not in {"electricity", "paytrail"}]
    proper = {w.casefold().rstrip(".?") for w in re.findall(r"\b[A-Z][\w@.-]+", question)}
    return words[0].rstrip(".?") if len(words) == 1 and words[0].rstrip(".?") in proper else None


def match(text, question):
    words = terms(question)
    # Generic contract questions may match stored electricity contract facts;
    # an unspecified invoice search must not become a mailbox-wide search.
    return (
        any(w in text.casefold() for w in words)
        if words
        else "contract" in question.casefold() or "sopimus" in question.casefold()
    )


def period(question):
    selected = requested_dates(question)
    return (
        (selected.date_from.isoformat(), selected.date_to.isoformat()) if selected else (None, None)
    )


def email_in_period(message_date, question):
    start, end = period(question)
    if not start:
        return True
    try:
        try:
            selected = datetime.fromisoformat(message_date).date()
        except ValueError:
            selected = parsedate_to_datetime(message_date).date()
        return date.fromisoformat(start) <= selected <= date.fromisoformat(end)
    except (ValueError, TypeError, OverflowError):
        # Undated evidence cannot establish existence within a requested period.
        return False


def knowledge_snapshot():
    """Resolve the signed active queue, never choose a snapshot by file mtime."""
    from tapio.confirmation.persistent import PersistentQueue

    queue = PersistentQueue(None)
    manifest = queue.manifest()
    if manifest["active"]:
        service = queue.service()
        directory = queue.root / "windows" / manifest["active"] / "knowledge"
        digest = service.batch["knowledge_hash"]
    else:
        directory = queue.root / "knowledge"
        digest = manifest["initial_knowledge_hash"]
    return load_bundle(directory / ("snapshot-" + digest + ".json"))


def local_evidence(question):
    records, sources = [], []
    # Existing replay validation and authority policy decide which claims qualify.
    try:
        queries = KnowledgeQueries(knowledge_snapshot())
        for item in queries.snapshot.items:
            claim = item.claim
            if claim.kind not in {
                Kind.CONTRACT_FACT,
                Kind.DOCUMENT_FACT,
                Kind.RELATIONSHIP,
                Kind.RECIPIENT_CONCEPT,
            } or not queries.accepted(item):
                continue
            if match(claim.subject + " " + claim.predicate + " " + str(claim.value), question):
                records.append(
                    {
                        "source": "Persistent knowledge",
                        "subject": claim.subject,
                        "kind": claim.kind.value,
                        "field": claim.predicate,
                        "value": claim.value,
                        "authority": claim.authority.value,
                        "references": [p.source_id for p in item.provenance],
                    }
                )
                if len(records) >= 20:
                    break
        sources.append(
            {
                "label": "Persistent knowledge",
                "status": "checked",
                "detail": "Accepted facts only; up to 20 matching records.",
            }
        )
    except (OSError, ValueError, KeyError, TypeError):
        sources.append(
            {
                "label": "Persistent knowledge",
                "status": "unavailable",
                "detail": "No verified active knowledge bundle could be read.",
            }
        )
    # Human-accepted email manifests are stored document knowledge, not fresh Gmail.
    try:
        selected = 0
        for path in sorted(GmailSettings().evidence.glob("*.json")):
            evidence = EmailEvidence.model_validate_json(path.read_text())
            if not match(evidence.sender + " " + evidence.subject, question):
                continue
            if not email_in_period(evidence.message_date, question):
                continue
            records.append(
                {
                    "source": "Stored email evidence",
                    "subject": evidence.subject,
                    "sender": evidence.sender,
                    "date": evidence.message_date,
                    "accepted_fields": evidence.accepted_fields,
                    "classification": evidence.source_classification,
                    "excerpt": evidence.body[:1600],
                    "reference": evidence.external_message_id,
                    "content_hash": evidence.content_hash,
                }
            )
            selected += 1
            if selected == 10:
                break
        sources.append(
            {
                "label": "Stored email evidence",
                "status": "checked",
                "detail": f"{selected} matching accepted records; not a live mailbox search.",
            }
        )
    except (OSError, ValueError):
        sources.append(
            {
                "label": "Stored email evidence",
                "status": "unavailable",
                "detail": "Accepted email records could not be validated.",
            }
        )
    engine = None
    try:
        vendor = subject(question)
        start, end = period(question)
        engine = readonly_engine()
        result = Queries(session_factory=lambda: readonly_session(engine)).documents(
            DocumentQuery(
                vendor=vendor if vendor and len(vendor) > 1 else None,
                document_type="invoice"
                if re.search(r"\b(invoice|receipt|lasku|kuitti)", question, re.I)
                else None,
                date_from=start,
                date_to=end,
                limit=20,
            )
        )
        docs = [d.model_dump(mode="json") for d in result.items]
        # No exact subject: retain only matching metadata, not unrelated documents.
        if not vendor:
            docs = [d for d in docs if match(str(d), question)]
        records.extend({"source": "Imported documents", **d} for d in docs)
        sources.append(
            {
                "label": "Imported documents",
                "status": "checked",
                "detail": f"{len(docs)} matching metadata records"
                + ("; results limited." if result.truncated else "."),
            }
        )
    except Exception:
        sources.append(
            {
                "label": "Imported documents",
                "status": "unavailable",
                "detail": "Local document lookup is unavailable.",
            }
        )
    finally:
        if engine is not None:
            engine.dispose()
    return records, sources


def gmail_query(question, records):
    """Derive bounded search from user scope or matching accepted email evidence."""
    sender = subject(question)
    try:
        dates = period(question)
    except ValueError:
        return None
    if not sender:
        senders = {
            re.search(r"[\w.+-]+@[\w.-]+", r.get("sender", ""))[0]
            for r in records
            if re.search(r"[\w.+-]+@[\w.-]+", r.get("sender", ""))
        }
        if len(senders) == 1:
            sender = next(iter(senders))
    if not sender or not dates[0]:
        return None
    # Search syntax comes from code, never from email bodies or LLM tool instructions.
    sender = re.sub(r"[^\w@.-]", "", sender)
    end = date.fromisoformat(dates[1]) + timedelta(days=1)
    query = f"from:{sender} after:{dates[0].replace('-', '/')} before:{end:%Y/%m/%d}"
    return Search(query=query, max_results=5)


async def gmail_lookup(search, audit_dir):
    async with asyncio.timeout(75), gmail_session() as session:
        registry = Registry(audit_path=audit_dir / "gmail-tools.jsonl")
        register_gmail(registry, session)
        if isinstance(search, Search):
            found = await registry.call("gmail_search_messages", search.model_dump(mode="json"))
            if not found["ok"]:
                raise ValueError(found["error"]["code"])
            selected = found["data"]["items"][:3]
            limited = found["data"]["more_available"] or len(found["data"]["items"]) > 3
        else:
            selected = [
                MessageID.model_validate(item).model_dump(mode="json") for item in search[:3]
            ]
            limited = len(search) > 3
        records = []
        for metadata in selected:
            response = await registry.call(
                "gmail_get_message", {"message_id": metadata["message_id"]}
            )
            if not response["ok"]:
                raise ValueError(response["error"]["code"])
            message = response["data"]
            records.append(
                {
                    "source": "Gmail read-only",
                    "subject": message["subject"],
                    "sender": message["sender"],
                    "date": message["message_date"],
                    "excerpt": message["body"][:1600],
                    "excerpt_limited": len(message["body"]) > 1600 or message["body_truncated"],
                    "reference": message["message_id"],
                    "content_hash": message["content_hash"],
                    "retrieved_at": message["retrieved_at"],
                    "attachments": [a["filename"] for a in message["attachments"]],
                }
            )
        return records, limited


def accepted_answer(question, records):
    """Only exact accepted contract fields may become a direct date answer."""
    q = question.casefold()
    requested = (
        "end"
        if re.search(r"\b(end|ends|expire|expires|expiry)\b", q)
        else "start"
        if re.search(r"\b(start|starts|begin|begins)\b", q)
        else None
    )
    if not requested:
        if re.search(r"\bdates\b", q):
            start = accepted_answer("contract start", records)
            end = accepted_answer("contract end", records)
            return start + " " + end if start and end else None
        return None
    values = []
    subjects = set()
    for record in records:
        if record.get("source") == "Persistent knowledge" and record.get("kind") != "CONTRACT_FACT":
            continue
        if record.get("source") == "Stored email evidence" and record.get("classification") not in {
            "CONTRACT_CONFIRMATION",
            "ACCEPTED_CONTRACT",
            "CONFIRMATION",
            "CONTRACT_PDF",
            "contract_confirmation",
        }:
            continue
        fields = record.get("accepted_fields", {})
        if record.get("source") == "Persistent knowledge":
            fields = {record.get("field", ""): record.get("value")}
        for key, value in fields.items():
            if (
                key.casefold()
                in {
                    requested + "_date",
                    "contract_" + requested + "_date",
                    "contract." + requested + "_date",
                }
                and isinstance(value, str)
                and re.fullmatch(r"(?:\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})", value)
            ):
                values.append(value)
                subjects.add(record.get("subject", ""))
    if len(set(values)) == 1 and len(subjects) == 1:
        return f"The stored accepted contract {requested} date is {values[0]}."
    return None


def existence_match(question, record):
    """A sender match alone cannot turn a contract into a receipt or invoice."""
    if re.search(r"\b(invoice|lasku)", question, re.I):
        return (
            record.get("source") == "Imported documents"
            and record.get("document_type") == "invoice"
        )
    if re.search(r"\b(receipt|kuitti)", question, re.I):
        return (
            record.get("source") == "Stored email evidence"
            and record.get("classification") == "RECEIPT"
        )
    if re.search(r"\b(contract|agreement|sopimus)", question, re.I):
        return record.get("classification") in {"CONFIRMATION", "CONTRACT_PDF"}
    return False


async def answer_question(
    pilot, question, *, local_loader=local_evidence, email_loader=gmail_lookup
):
    started = time.monotonic()
    evidence_question = bool(EVIDENCE.search(question))
    purpose = (
        bool(PURPOSE.search(question))
        and bool(re.search(r"\b(purpose|why|what.*(?:for|payment)|recipient)\b", question, re.I))
        and not CALCULATION.search(question)
    )
    # Arithmetic, aggregates and ordinary bank searches keep the validated engine.
    if CALCULATION.search(question) or not (evidence_question or purpose):
        result = await pilot.ask(question, route="POST /pilot/ask")
        sources = [
            {
                "label": "Local structured data",
                "status": "used" if result.evidence else "checked",
                "detail": "Deterministic tools; Gmail was not searched.",
            }
        ]
        return result.model_copy(update={"sources": sources})
    try:
        period(question)
    except ValueError:
        session = Session(
            id=str(uuid4()),
            timestamp=datetime.now(UTC).isoformat(),
            model_calls=0,
            rounds=0,
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            latency_seconds=0,
            estimated_cost_usd="0",
        )
        result = PilotResponse(
            answer="Specify one calendar year, or one month and year.",
            direct_answer="Specify one calendar year, or one month and year.",
            evidence_state="NEEDS_NARROWING",
            evidence_states=["NEEDS_NARROWING"],
            coverage=Coverage(status="UNAVAILABLE"),
            evidence=[],
            human_review=[],
            limitations=["No evidence search was run because the requested period is unsupported."],
            suggestions=["For example: Find invoices from Vattenfall in October 2025."],
            session=session,
        )
        pilot.history.save(
            session.id, {"question": question, "response": result.model_dump(mode="json")}
        )
        return result
    base = await pilot.ask(question, route="POST /pilot/ask") if purpose else None
    records, sources = await asyncio.to_thread(local_loader, question)
    if base:
        sources.insert(
            0,
            {
                "label": "Local structured data",
                "status": "used" if base.evidence else "checked",
                "detail": "Bank evidence checked before document/email lookup.",
            },
        )
    for source in sources:
        if any(record.get("source") == source["label"] for record in records):
            source["status"] = "partially used" if source["status"] == "unavailable" else "used"
    direct = accepted_answer(question, records)
    explicit_mail = bool(re.search(r"\b(gmail|email|message)\b", question, re.I))
    # Document existence can be satisfied locally; metadata cannot establish dates/purpose.
    existence = bool(
        re.search(r"\b(have|find|exist|show|list)\b", question, re.I)
    ) and not re.search(r"\b(when|date|purpose|why)\b", question, re.I)
    sufficient = bool(direct) or (existence and any(existence_match(question, r) for r in records))
    session = (
        base.session
        if base
        else Session(
            id=str(uuid4()),
            timestamp=datetime.now(UTC).isoformat(),
            model_calls=0,
            rounds=0,
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            latency_seconds=0,
            estimated_cost_usd="0",
        )
    )
    directory = pilot.history.directory(session.id)
    limitations = []
    suggestions = []
    if explicit_mail or not sufficient:
        search = gmail_query(question, records)
        known_messages = [
            {"message_id": record["reference"]}
            for record in records
            if record.get("source") == "Stored email evidence" and record.get("reference")
        ]
        lookup = search or known_messages[:3]
        if lookup:
            try:
                email, limited = await email_loader(lookup, directory)
                records.extend(email)
                sources.append(
                    {
                        "label": "Gmail read-only",
                        "status": "used" if email else "checked",
                        "detail": f"{len(email)} candidate messages; "
                        + (
                            "sender and date bounded."
                            if search
                            else "selected stored message references only."
                        ),
                    }
                )
                limitations.append(
                    "Email matches are candidates, not proof of a contract, receipt or "
                    "payment purpose. No attachment was downloaded or imported."
                )
                if limited:
                    limitations.append(
                        "Email results are limited; refine the sender or period "
                        "for more precise evidence."
                    )
            except Exception:
                sources.append(
                    {
                        "label": "Gmail read-only",
                        "status": "unavailable",
                        "detail": "Email lookup could not complete. "
                        "Check the existing Gmail connection and try again.",
                    }
                )
                limitations.append(
                    "Gmail evidence is unavailable; this answer does not establish that an "
                    "email or receipt is absent."
                )
        else:
            sources.append(
                {
                    "label": "Gmail read-only",
                    "status": "needs scope",
                    "detail": "A sender and calendar year are needed "
                    "for the existing bounded email search.",
                }
            )
            suggestions.append(
                "Include the sender or provider and a calendar year, for example: Do I "
                "have invoices from Vattenfall in 2025?"
            )
    else:
        sources.append(
            {
                "label": "Gmail read-only",
                "status": "not searched",
                "detail": "Stored evidence is sufficient for this lookup.",
            }
        )
    if not direct:
        direct = (
            f"Found {len(records)} relevant evidence records to inspect."
            if records
            else "I could not establish an answer from the available evidence."
        )
    if not sufficient:
        limitations.append(
            "The requested fact is not established. Review the supporting evidence "
            "or narrow the question; no classification or tax conclusion was made."
        )
    if purpose:
        limitations.append(
            "A payment intermediary or sender identity alone does not establish the "
            "purchase purpose."
        )
    state = "PARTIAL_COVERAGE" if records else "NEEDS_NARROWING" if suggestions else "UNAVAILABLE"
    if not records and not suggestions and sources and sources[-1]["status"] == "checked":
        state = "NO_MATCH"
        limitations.append(
            "No match in the bounded search is not proof of absence from the mailbox."
        )
    if sufficient:
        state = "SUPPORTED"
    result = PilotResponse(
        answer=direct,
        direct_answer=direct,
        evidence_state=state,
        evidence_states=[state],
        coverage=Coverage(status="DETERMINED" if records else "UNAVAILABLE"),
        evidence=[],
        human_review=[],
        limitations=limitations,
        session=session,
        suggestions=suggestions,
        evidence_summary=[
            f"{r['source']}: {r.get('subject') or r.get('vendor') or r.get('id', 'Record')}"
            for r in records
        ],
        sources=sources,
        supporting_records=records,
    )
    if base:
        result = result.model_copy(
            update={
                "optional_details": base.optional_details,
                "relevant_breakdown": [base.direct_answer or base.answer]
                if base.direct_answer or base.answer
                else [],
            }
        )
    result = result.model_copy(
        update={
            "session": session.model_copy(
                update={"latency_seconds": round(time.monotonic() - started, 6)}
            )
        }
    )
    # Preserve the accepted pilot's append-only original record. Supplement separately.
    if base:
        from integrations.gmail.cache import private_write

        private_write(directory / "workspace-evidence.json", result.model_dump_json().encode())
    else:
        pilot.history.save(
            session.id,
            {
                "question": question,
                "response": result.model_dump(mode="json"),
                "route": "WORKSPACE_EVIDENCE",
            },
        )
    return result

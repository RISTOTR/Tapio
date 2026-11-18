"""Read-only preview, explicit import, durable recovery, and ongoing Review handoff."""

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

import pandera as pa
from sqlalchemy import select

from apps.api.app.domain.models import Document, ImportRun, Transaction
from data_pipeline.ingest.bank_csv import SOURCE_TYPE, BankInputError
from data_pipeline.labels.snapshot import fingerprint
from data_pipeline.load.bank import BankImportResult, import_bank_bytes
from data_pipeline.normalize.sampo import SOURCE_TYPE as SAMPO_TYPE
from data_pipeline.normalize.sampo import adapter, sampo_account
from data_pipeline.validate.bank import bank_enriched_schema
from integrations.gmail.cache import private_write
from tapio.confirmation.groups import GroupReview
from tapio.confirmation.persistent import LOCK
from tapio.confirmation.source_updates import accept_bank_import, accepted_fingerprints
from tapio.knowledge.models import digest

MAX_BYTES = 10 * 1024 * 1024
ERRORS = {
    "unsupported_sampo_headers": "Choose a Sampo transaction CSV export with the original columns.",
    "multiple_sampo_accounts": "Export one Sampo account per file.",
    "unsupported_sampo_currency_or_source": "This importer supports SAMPO exports in EUR only.",
    "invalid_sampo_csv": "Choose a UTF-8, comma-separated Sampo CSV.",
    "unsupported_bank_headers": (
        "This CSV does not match the supported Finnish bank export columns."
    ),
    "invalid_utf8_or_csv": "The file must be a UTF-8, semicolon-separated bank CSV.",
    "empty_source": "The file has no transactions.",
    "incomplete_source_row": "One or more rows have missing columns.",
    "archive_id_content_conflict": (
        "A transaction identifier already exists with different source "
        "fields. Nothing was imported."
    ),
    "fingerprint_account_mismatch": (
        "This file was already imported under a different account. Select that account."
    ),
}


def plain(value):
    return json.loads(json.dumps(value, default=str))


def review_summary(plan, ids):
    cards = [c for c in plan["cards"] if c["transaction"]["id"] in ids]
    card_ids = {c["card_id"] for c in cards}
    groups = [g for g in plan["groups"] if set(g["card_ids"]) & card_ids]
    excluded = [c for c in plan["excluded"] if c["transaction_id"] in ids]
    individual = set(plan["individual_ids"]) & card_ids
    return {
        "recognized": sum(bool(c.get("review_analysis", {}).get("known_entity")) for c in cards),
        "quick_confirmations": sum(len(g["card_ids"]) == 1 for g in groups),
        "grouped_confirmations": sum(len(g["card_ids"]) > 1 for g in groups),
        "individual_judgment": len(individual),
        "evidence_limited": len(excluded)
        + sum(
            c["card_id"] in individual and not c.get("review_analysis", {}).get("proposal")
            for c in cards
        ),
        "review_items": len(card_ids) + len(excluded),
        "pending_total": plan["summary"]["total_pending"],
    }


class ImportWorkflow:
    def __init__(self, queue, root=None):
        self.queue = queue
        self.root = Path(root) if root else queue.root / "browser_imports"
        self.previews = {}

    def read_tables(self):
        with self.queue.factory() as db:
            return plain(
                {
                    name: [dict(r) for r in db.execute(select(table)).mappings()]
                    for name, table in Document.metadata.tables.items()
                }
            )

    def accounts(self):
        with self.queue.factory() as db:
            namespaces = db.scalars(select(Transaction.source_namespace).distinct()).all()
        prefix = SOURCE_TYPE + ":"
        return sorted(n[len(prefix) :] for n in namespaces if n and n.startswith(prefix))

    def sign(self, value):
        return hmac.new(
            (self.queue.root / "queue.key").read_bytes(), digest(value).encode(), hashlib.sha256
        ).hexdigest()

    def save(self, job, data):
        private_write(
            self.root / job / "job.json",
            json.dumps({"data": data, "signature": self.sign(data)}).encode(),
        )

    def load(self, job):
        if len(job) != 64 or any(c not in "0123456789abcdef" for c in job):
            raise ValueError("INVALID_IMPORT_TOKEN")
        envelope = json.loads((self.root / job / "job.json").read_text())
        if not hmac.compare_digest(envelope["signature"], self.sign(envelope["data"])):
            raise ValueError("IMPORT_JOURNAL_INTEGRITY")
        return envelope["data"]

    def history(self):
        results, pending = [], []
        for path in sorted(
            self.root.glob("*/job.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            data = self.load(path.parent.name)
            if data.get("outcome"):
                results.append(data["outcome"])
            else:
                pending.append({"token": path.parent.name, "filename": data["filename"]})
        represented = {r.get("import_run_id") for r in results}
        with self.queue.factory() as db:
            runs = db.scalars(
                select(ImportRun)
                .where(
                    ImportRun.source_type.in_([SOURCE_TYPE, SAMPO_TYPE]),
                    ImportRun.status == "completed",
                )
                .order_by(ImportRun.started_at.desc())
                .limit(10)
            ).all()
            dates = {}
            for run_id, day in db.execute(
                select(Transaction.import_run_id, Transaction.booking_date)
            ):
                dates.setdefault(str(run_id), []).append(day)
            for run in runs:
                if str(run.id) in represented:
                    continue
                days = dates.get(str(run.id), [])
                meta = run.source_metadata
                results.append(
                    {
                        "import_run_id": str(run.id),
                        "imported_at": run.completed_at.isoformat(),
                        "filename": run.source_filename,
                        "rows_read": meta.get("rows_parsed", run.row_count),
                        "new_rows": run.row_count,
                        "duplicates": meta.get("rows_skipped_duplicates", 0),
                        "date_from": str(min(days)) if days else None,
                        "date_to": str(max(days)) if days else None,
                        "review_items": None,
                    }
                )
        results.sort(key=lambda r: r["imported_at"], reverse=True)
        return {"recent": results[:10], "pending": pending}

    def preview(self, raw, filename, account, sid, source_type=SOURCE_TYPE):
        if not raw or len(raw) > MAX_BYTES:
            return {
                "validation": "INVALID",
                "message": "Choose a non-empty CSV no larger than 10 MB.",
            }
        filename = Path(filename.replace("\\", "/")).name
        if not filename or len(filename) > 200:
            return {"validation": "INVALID", "message": "Use a filename of 1–200 characters."}
        if source_type == SOURCE_TYPE and account not in self.accounts():
            raise ValueError("SELECT_EXISTING_ACCOUNT")
        try:
            parser_version, normalize = adapter(source_type)
            frame = normalize(raw, filename)
            account_name = account
            if source_type == SAMPO_TYPE:
                account_name, account = sampo_account(frame)
            bank_enriched_schema.validate(frame)
            namespace = source_type + ":" + account
            with self.queue.factory() as db:
                existing = {
                    t.source_transaction_id: t.raw_source
                    for t in db.scalars(
                        select(Transaction).where(Transaction.source_namespace == namespace)
                    )
                }
                previous = db.scalars(
                    select(ImportRun).where(
                        ImportRun.sha256 == hashlib.sha256(raw).hexdigest(),
                        ImportRun.source_type == source_type,
                        ImportRun.parser_version == parser_version,
                    )
                ).all()
                if any(
                    r.source_metadata.get("outcome") == "imported"
                    and r.source_metadata.get("source_namespace") != namespace
                    for r in previous
                ):
                    raise BankInputError("fingerprint_account_mismatch")
            new, duplicates = [], []
            for row in frame.iter_rows(named=True):
                identity = row["source_transaction_id"]
                source = json.loads(row["raw_source"])
                duplicate = identity in existing
                if duplicate and existing[identity] != source:
                    raise BankInputError("archive_id_content_conflict")
                existing[identity] = source
                item = {
                    "date": str(row["booking_date"]),
                    "merchant": row.get("raw_counterparty"),
                    "amount": str(row["amount"]),
                    "currency": row["currency"],
                }
                (duplicates if duplicate else new).append(item)
        except (BankInputError, pa.errors.SchemaError, pa.errors.SchemaErrors, ValueError) as exc:
            code = str(exc) if isinstance(exc, BankInputError) else "invalid_values"
            return {
                "validation": "UNSUPPORTED" if code == "unsupported_bank_headers" else "INVALID",
                "message": ERRORS.get(
                    code,
                    (
                        "A date, amount or required field is invalid. Check the bank "
                        "export and try again."
                    ),
                ),
            }
        summary = {
            "validation": "VALID",
            "filename": filename,
            "bytes": len(raw),
            "schema": ("Sampo CSV · " if source_type == SAMPO_TYPE else "Finnish bank CSV · ")
            + parser_version,
            "account": account_name,
            "rows_read": frame.height,
            "duplicates": len(duplicates),
            "new_rows": len(new),
            "date_from": str(frame["booking_date"].min()),
            "date_to": str(frame["booking_date"].max()),
            "new_preview": new[:50],
            "duplicate_preview": duplicates[:50],
            "details_limited": len(new) > 50 or len(duplicates) > 50,
        }
        with LOCK:
            GroupReview(self.queue).verify_sources()
            now = time.time()
            self.previews = {k: v for k, v in self.previews.items() if v["expires"] > now}
            if len(self.previews) >= 8:
                self.previews.pop(next(iter(self.previews)))
            token = secrets.token_hex(32)
            self.previews[token] = {
                "raw": raw,
                "filename": filename,
                "account": account,
                "source_type": source_type,
                "sid": sid,
                "expires": now + 900,
                "summary": summary,
                "state": digest(self.read_tables()),
            }
        return {**summary, "token": token}

    def commit(self, token, sid):
        if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("INVALID_IMPORT_TOKEN")
        with LOCK:
            if not self.queue.enabled():
                raise ValueError("IMPORT_WRITES_DISABLED")
            if (self.root / token / "job.json").exists() and len(token) == 64:
                job = self.load(token)
                if job.get("outcome"):
                    return job["outcome"]
            else:
                preview = self.previews.get(token)
                if not preview or preview["sid"] != sid or preview["expires"] < time.time():
                    raise ValueError("IMPORT_PREVIEW_EXPIRED")
                if self.history()["pending"]:
                    raise ValueError("IMPORT_RECOVERY_REQUIRED")
                GroupReview(self.queue).verify_sources()
                before = self.read_tables()
                if digest(before) != preview["state"]:
                    raise ValueError("IMPORT_PREVIEW_STALE")
                from datetime import UTC, datetime

                job = {k: preview[k] for k in ("filename", "account", "summary", "source_type")}
                job.update(
                    before=before,
                    sha256=hashlib.sha256(preview["raw"]).hexdigest(),
                    started_at=datetime.now(UTC).isoformat(),
                )
                # Journal only after the deliberate action, before the loader writes.
                private_write(self.root / token / "source.csv", preview["raw"])
                self.save(token, job)
            raw = (self.root / token / "source.csv").read_bytes()
            if hashlib.sha256(raw).hexdigest() != job["sha256"]:
                raise ValueError("IMPORT_SOURCE_CHANGED")
            ids = set()
            if job["summary"]["new_rows"]:
                if not job.get("result"):
                    current = self.read_tables()
                    old_runs = {r["id"] for r in job["before"]["import_runs"]}
                    added = [r for r in current["import_runs"] if r["id"] not in old_runs]
                    if added:
                        # Recover a loader commit interrupted before journal completion.
                        if len(added) != 1 or added[0]["sha256"] != job["sha256"]:
                            raise ValueError("IMPORT_RECOVERY_CONFLICT")
                        run = added[0]
                        result = BankImportResult(
                            status=run["source_metadata"]["outcome"],
                            source_file=run["source_filename"],
                            rows_parsed=run["source_metadata"]["rows_parsed"],
                            rows_loaded=run["row_count"],
                            rows_skipped_duplicates=run["source_metadata"][
                                "rows_skipped_duplicates"
                            ],
                            parser_version=run["parser_version"],
                            sha256=run["sha256"],
                            import_run_id=run["id"],
                            error_code=run["source_metadata"].get("error_code"),
                        )
                    else:
                        if digest(current) != digest(job["before"]):
                            raise ValueError("IMPORT_RECOVERY_CONFLICT")
                        source_type = job.get("source_type", SOURCE_TYPE)
                        parser_version, normalize = adapter(source_type)
                        result = import_bank_bytes(
                            raw,
                            source_filename=job["filename"],
                            account_key=job["account"],
                            session_factory=self.queue.factory,
                            source_type=source_type,
                            parser_version=parser_version,
                            normalize=normalize,
                        )
                    job["result"] = result.model_dump(mode="json")
                    self.save(token, job)
                result = BankImportResult.model_validate(job["result"])
                if result.status != "imported":
                    raise ValueError("IMPORT_REQUIRES_RECONCILIATION")
                accepted_path = (
                    self.queue.root / "source_acceptances" / (str(result.import_run_id) + ".json")
                )
                if accepted_path.exists() and self.queue.manifest()["source_fingerprints"] != {
                    n: fingerprint(job["before"][n])
                    for n in self.queue.manifest()["source_fingerprints"]
                }:
                    accepted_fingerprints(self.queue, {})
                    envelope = json.loads(accepted_path.read_text())
                    if not hmac.compare_digest(envelope["signature"], self.sign(envelope["data"])):
                        raise ValueError("IMPORT_JOURNAL_INTEGRITY")
                    acceptance = envelope["data"]
                else:
                    acceptance = accept_bank_import(
                        self.queue, job["before"], self.read_tables(), result, raw
                    )
                ids = set(acceptance["new_transaction_ids"])
            plan = GroupReview(self.queue).build()
            counts = review_summary(plan, ids)
            outcome = {
                k: job["summary"][k]
                for k in ("filename", "rows_read", "duplicates", "new_rows", "date_from", "date_to")
            }
            outcome.update(
                counts,
                import_run_id=str(result.import_run_id) if ids else None,
                imported_at=job["started_at"],
                complete=True,
                message="Import complete."
                if ids
                else "Nothing new was added. All transactions were already imported.",
            )
            job["outcome"] = outcome
            self.save(token, job)
            self.previews.pop(token, None)
            return outcome

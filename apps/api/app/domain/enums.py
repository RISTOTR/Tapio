from enum import StrEnum


class ImportStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TransactionDirection(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class BusinessContext(StrEnum):
    PERSONAL = "personal"
    PROPERTY = "property"
    FORESTRY = "forestry"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class DocumentType(StrEnum):
    INVOICE = "invoice"
    TIMBER_SALE = "timber_sale"
    BANK_STATEMENT = "bank_statement"
    OTHER = "other"


class TaxReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    LIKELY_BUSINESS_EXPENSE = "likely_business_expense"
    LIKELY_PERSONAL = "likely_personal"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED_BUSINESS_EXPENSE = "confirmed_business_expense"
    CONFIRMED_NON_BUSINESS = "confirmed_non_business"


class TransactionCategory(StrEnum):
    ELECTRICITY = "ELECTRICITY"
    GRID_DISTRIBUTION = "GRID_DISTRIBUTION"
    FORESTRY_SERVICE = "FORESTRY_SERVICE"
    TIMBER_INCOME = "TIMBER_INCOME"
    TAX = "TAX"
    GROCERIES = "GROCERIES"
    FUEL = "FUEL"
    TRAVEL = "TRAVEL"
    INSURANCE = "INSURANCE"
    MAINTENANCE = "MAINTENANCE"
    TRANSFER = "TRANSFER"
    SUBSCRIPTION = "SUBSCRIPTION"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class LabelReviewStatus(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"
    SKIPPED_AMBIGUOUS = "SKIPPED_AMBIGUOUS"

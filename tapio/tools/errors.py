"""Stable codes only; never send backend exceptions or credentials to a model."""

from enum import StrEnum

from .schemas import Schema


class ErrorCode(StrEnum):
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    SCOPE_REJECTED = "SCOPE_REJECTED"
    GMAIL_API_FAILURE = "GMAIL_API_FAILURE"
    NO_MATCHING_MESSAGES = "NO_MATCHING_MESSAGES"
    ATTACHMENT_MISSING = "ATTACHMENT_MISSING"
    UNSUPPORTED_MIME_TYPE = "UNSUPPORTED_MIME_TYPE"
    INVALID_GMAIL_QUERY = "INVALID_GMAIL_QUERY"
    DOCUMENT_PARSER_UNSUPPORTED = "DOCUMENT_PARSER_UNSUPPORTED"
    TARIFF_COVERAGE_MISSING = "TARIFF_COVERAGE_MISSING"
    AMBIGUOUS_RECONCILIATION = "AMBIGUOUS_RECONCILIATION"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    MODEL_TOOL_SCHEMA_ERROR = "MODEL_TOOL_SCHEMA_ERROR"
    NOT_FOUND = "NOT_FOUND"
    INCOMPLETE_COVERAGE = "INCOMPLETE_COVERAGE"
    OUTPUT_LIMIT = "OUTPUT_LIMIT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    UNSUPPORTED_REQUEST = "UNSUPPORTED_REQUEST"


class ToolFailure(Exception):
    def __init__(self, code: ErrorCode):
        self.code = code
        super().__init__(code.value)


class SafeError(Schema):
    code: ErrorCode
    message: str


def safe_error(code):
    return SafeError(code=code, message=code.value.replace("_", " ").capitalize())

"""Domain errors mapped to HTTP responses by the API layer."""
from __future__ import annotations

from typing import Any, Dict, Optional


class DomainError(Exception):
    """Base class for errors caused by the caller rather than by a defect."""

    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ValidationError(DomainError):
    status_code = 422
    code = "validation_error"


class ConflictError(DomainError):
    """The request conflicts with the current state of the resource."""

    status_code = 409
    code = "conflict"


class AllocationError(ValidationError):
    """A stock-receipt allocation broke one of the compulsory settlement rules."""

    code = "allocation_error"

"""API Service exceptions"""

from __future__ import annotations


class ServiceError(Exception):
    """Base service exception"""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }


class NotFoundError(ServiceError):
    """Resource not found"""

    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            message=f"{resource_type} not found: {resource_id}",
            details={"resource_type": resource_type, "resource_id": resource_id},
        )


class ValidationError(ServiceError):
    """Validation failure"""

    def __init__(self, message: str, field: str | None = None):
        details = {"field": field} if field else {}
        super().__init__(message=message, details=details)


class ConflictError(ServiceError):
    """Resource conflict (e.g., duplicate)"""

    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            message=f"{resource_type} already exists: {resource_id}",
            details={"resource_type": resource_type, "resource_id": resource_id},
        )

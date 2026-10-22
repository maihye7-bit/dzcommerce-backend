"""
Service-layer exceptions for business logic errors.
"""


class ServiceError(Exception):
    """Base class for all service-layer (business logic) errors."""


class NotFoundError(ServiceError):
    """Raised when a requested resource does not exist, or does not
    belong to the store it was requested under."""


class DuplicateSKUError(ServiceError):
    """Raised when a product SKU is already used by another product."""


class ValidationError(ServiceError):
    """Raised for business-rule violations not already caught by the
    Pydantic schema layer."""


# Phase 5: Order-specific exceptions


class OrderStateError(ServiceError):
    """Raised when an invalid order state transition is attempted."""


class InsufficientInventoryError(ServiceError):
    """Raised when there is not enough stock to fulfill an order."""


class OrderNotModifiableError(ServiceError):
    """Raised when trying to modify an order that is no longer in DRAFT state."""

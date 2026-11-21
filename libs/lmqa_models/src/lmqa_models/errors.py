"""Service errors. The gateway maps each to its HTTP status; messages are safe to show to the caller."""

from __future__ import annotations


class ServiceError(Exception):
    status = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BadRequest(ServiceError):
    status = 400


class Forbidden(ServiceError):
    status = 403


class NotFound(ServiceError):
    status = 404


class Conflict(ServiceError):
    status = 409


class TooLarge(ServiceError):
    status = 413


class TooManyRequests(ServiceError):
    status = 429


class Unavailable(ServiceError):
    """A dependency failed and nothing was released (fail closed)."""

    status = 503

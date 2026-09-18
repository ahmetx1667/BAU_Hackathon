"""Control-flow exceptions the request dispatcher turns into responses.

Validation happens deep inside helpers, far from the handler that knows how to
reply. Raising one of these lets a helper abort the request and say where the
user should land, without every caller having to thread an error return upward.
"""

from __future__ import annotations


class AuthRequired(Exception):
    """Raised when an anonymous visitor reaches a page that needs a login."""


class CsrfError(Exception):
    """Raised when a POST arrives without a CSRF token matching the session."""


class ValidationError(Exception):
    """Raised when submitted data is rejected.

    `redirect_to` is the page the user is sent back to, with the message shown
    as a flash — so the error appears on the form that caused it.
    """

    def __init__(self, message: str, redirect_to: str) -> None:
        super().__init__(message)
        self.redirect_to = redirect_to

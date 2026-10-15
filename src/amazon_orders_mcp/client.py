"""Shared error type for the Amazon Orders MCP server.

Raised when Amazon needs a fresh sign-in: an expired session, or a challenge
that cannot be answered without a browser. The server maps it to the
`refresh_session` tool.
"""


class NonInteractiveAuthRequired(RuntimeError):
    """Raised when Amazon needs a fresh sign-in (expired session or challenge)."""

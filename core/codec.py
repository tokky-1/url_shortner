"""Base62 encoding for short codes.

This wrapper exists for validation. pybase62 is permissive in two ways that
are dangerous here, both verified against pybase62 1.0.0:

    base62.decode("") -> 0      a request for "/" would resolve to ID 0
    base62.encode(-1) -> "0"    every negative ID collapses onto ID 0

Neither raises. Both are caught here instead.
"""

import base62


def encode(n: int) -> str:
    """Encode a non-negative integer ID as a short code."""
    if n < 0:
        raise ValueError(f"n must be non-negative, got {n}")
    return base62.encode(n)


def decode(code: str) -> int:
    """Decode a short code back to its integer ID."""
    if not code:
        raise ValueError("code must not be empty")
    return base62.decode(code)

"""Random tokens and codes from :mod:`secrets` (never from the seeded temperature generator)."""

from __future__ import annotations

import hashlib
import secrets

# No look-alike characters (0/O, 1/I/L) so a person can retype the code from the screen.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8
_TOKEN_BYTES = 32


class RandomSecretIssuer:
    """Tokens have 256 bits of entropy, so a fast SHA-256 digest is enough for storage."""

    def new_token(self) -> str:
        """URL-safe token for devices and sessions."""
        return secrets.token_urlsafe(_TOKEN_BYTES)

    def new_code(self) -> str:
        """Short binding code."""
        return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))

    def digest(self, secret: str) -> str:
        """Hex SHA-256 stored in the database."""
        return hashlib.sha256(secret.encode()).hexdigest()

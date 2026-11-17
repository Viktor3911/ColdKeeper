"""Password hashing with ``hashlib.scrypt`` (standard library, no extra dependency)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

_PREFIX = "scrypt"
_SALT_BYTES = 16
_KEY_BYTES = 32
_PARTS = 6


@dataclass(frozen=True, slots=True)
class ScryptParameters:
    """Work factors. The default is one of the equal-strength OWASP rows with moderate memory.

    OWASP lists N=2^17, r=8, p=1 (128 MiB) and equivalents trading memory for parallelism; N=2^15, r=8, p=3
    needs ~32 MiB per hash, which suits a small VPS. ``maxmem`` must be set explicitly: hashlib's default is
    too low for these values.
    """

    n: int = 2**15
    r: int = 8
    p: int = 3

    @property
    def maxmem(self) -> int:
        """Memory limit passed to hashlib with headroom."""
        return 128 * self.r * self.n * 2 + 1024 * 1024


class ScryptPasswordHasher:
    """Stores ``scrypt$n$r$p$salt$hash`` so parameters can be raised later and old hashes still verify."""

    def __init__(self, parameters: ScryptParameters | None = None) -> None:
        self._parameters = parameters or ScryptParameters()

    def hash(self, password: str) -> str:
        """Hash with a fresh random salt."""
        salt = secrets.token_bytes(_SALT_BYTES)
        key = self._derive(password, salt, self._parameters)
        params = self._parameters
        return "$".join([_PREFIX, str(params.n), str(params.r), str(params.p), _b64(salt), _b64(key)])

    def verify(self, password: str, encoded: str) -> bool:
        """Constant-time comparison; malformed hashes never match."""
        parsed = _parse(encoded)
        if parsed is None:
            return False
        parameters, salt, expected = parsed
        return hmac.compare_digest(self._derive(password, salt, parameters), expected)

    def needs_rehash(self, encoded: str) -> bool:
        """Whether the hash was made with other parameters."""
        parsed = _parse(encoded)
        return parsed is None or parsed[0] != self._parameters

    @staticmethod
    def _derive(password: str, salt: bytes, parameters: ScryptParameters) -> bytes:
        return hashlib.scrypt(
            password.encode(),
            salt=salt,
            n=parameters.n,
            r=parameters.r,
            p=parameters.p,
            maxmem=parameters.maxmem,
            dklen=_KEY_BYTES,
        )


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _parse(encoded: str) -> tuple[ScryptParameters, bytes, bytes] | None:
    parts = encoded.split("$")
    if len(parts) != _PARTS or parts[0] != _PREFIX:
        return None
    try:
        parameters = ScryptParameters(n=int(parts[1]), r=int(parts[2]), p=int(parts[3]))
        return parameters, _unb64(parts[4]), _unb64(parts[5])
    except ValueError:
        return None

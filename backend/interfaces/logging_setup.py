"""Logging that never writes device tokens: they travel in the ingest URL query string."""

from __future__ import annotations

import logging
import re

_TOKEN = re.compile(r"(token=)[^&\s\"']+", re.IGNORECASE)


def redact(text: str) -> str:
    """Replace ``token=<value>`` with ``token=***``."""
    return _TOKEN.sub(r"\1***", text)


class RedactTokensFilter(logging.Filter):
    """Rewrites the message and arguments of every record (uvicorn access log passes the path as an argument)."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Always keep the record, but with tokens removed."""
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(arg) if isinstance(arg, str) else arg for arg in record.args)
        return True


def configure_logging(level: str) -> None:
    """Root logging plus the redaction filter on handlers of uvicorn and our loggers."""
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token_filter = RedactTokensFilter()
    for name in ("", "uvicorn", "uvicorn.access", "uvicorn.error", "backend"):
        logger = logging.getLogger(name)
        logger.addFilter(token_filter)
        for handler in logger.handlers:
            handler.addFilter(token_filter)

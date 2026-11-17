"""Write (or verify) the OpenAPI schema the frontend types are generated from — no server or database needed.

``python -m backend.interfaces.http.openapi_export frontend/src/api/openapi.json [--check]``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.composition import build_container
from backend.interfaces.http.app import create_app
from backend.settings import Settings


def schema_text() -> str:
    """Stable, sorted JSON of the API schema (creating the app does not connect to the database)."""
    app = create_app(build_container(Settings(_env_file=None)))
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="OpenAPI-схема для типов frontend")
    parser.add_argument("path", type=Path)
    parser.add_argument("--check", action="store_true", help="только проверить, что файл актуален")
    args = parser.parse_args(argv)
    text = schema_text()
    if args.check:
        current = args.path.read_text(encoding="utf-8") if args.path.exists() else ""
        if current != text:
            sys.stderr.write(f"{args.path} устарел: выполните `task api-types`\n")
            return 1
        return 0
    args.path.parent.mkdir(parents=True, exist_ok=True)
    args.path.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

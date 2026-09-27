"""Content-based URLs keep HTML and its entire ES module graph on one release."""

import hashlib
from pathlib import Path

from fastapi.responses import HTMLResponse


def frontend_revision(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix in {".js", ".css", ".html"}:
            digest.update(path.relative_to(directory).as_posix().encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()[:20]


def frontend_page(directory: Path, name: str, revision: str) -> HTMLResponse:
    html = (directory / name).read_text(encoding="utf-8")
    # Only rewrite the fixed asset prefix in our trusted templates.
    return HTMLResponse(html.replace('"/assets/', f'"/assets/{revision}/'))

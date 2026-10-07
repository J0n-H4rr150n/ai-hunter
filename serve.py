#!/usr/bin/env python3
"""
AI Hunter — single-port host for phone/Tailscale access.

The Docker setup splits the UI (:33004) and the API (:33003), which means two origins
and plain HTTP — awkward from a phone and a mixed-content problem behind TLS. This
entrypoint serves the SPA and the API from one TLS origin instead, so the whole app is
reachable at https://<tailscale-host>:30170/ with same-origin API calls.

Run:
    docker compose up -d postgres redis          # dependencies only
    PORT=30170 python3 serve.py

TLS uses the shared dev cert if present, otherwise it falls back to HTTP.
"""
import io
import os
from pathlib import Path

import uvicorn
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi import Request

HERE = Path(__file__).resolve().parent

# Native runs reach Postgres/Redis on their published host ports, not container names.
os.environ.setdefault("DATABASE_URL", "postgresql://hunter:hunter_pass_dev@127.0.0.1:33001/ai_hunter")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:33002")

from backend.main import app  # noqa: E402  (must follow the env defaults above)

STATIC = Path(os.environ.get("STATIC_DIR", HERE / "frontend" / "public"))
PORT = int(os.environ.get("PORT", "30170"))
TLS_CERT = os.environ.get("TLS_CERT", str(Path.home() / "models" / "spa" / "certs" / "server.crt"))
TLS_KEY = os.environ.get("TLS_KEY", str(Path.home() / "models" / "spa" / "certs" / "server.key"))
APP_NAME = os.environ.get("APP_NAME", "AI Hunter")

_NO_CACHE = {"Cache-Control": "no-store, max-age=0"}

# The UI is hand-edited vanilla JS; never let a phone cache a stale module graph.
_ALWAYS_REVALIDATE = (".html", ".js", ".css", ".json")


def _revalidate(path: str) -> bool:
    return path.endswith(_ALWAYS_REVALIDATE)


def _icon(size: int) -> bytes:
    """Render the home-screen icon so there are no missing-asset 404s on mobile."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (size, size), "#111827")
    d = ImageDraw.Draw(img)
    pad = size // 8
    d.ellipse([pad, pad, size - pad, size - pad], fill="#f59e0b")
    bar = size // 10
    for i in range(3):
        y = size // 2 - bar + i * bar
        d.rectangle([pad * 2, y, size - pad * 2, y + bar // 2], fill="#111827")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@app.get("/manifest.json")
def manifest(request: Request):
    base = str(request.base_url)
    return JSONResponse({
        "name": APP_NAME,
        "short_name": "AI Hunter",
        "start_url": base,
        "scope": base,
        "id": base,
        "display": "standalone",
        "display_override": ["standalone", "fullscreen"],
        "orientation": "portrait",
        "background_color": "#111827",
        "theme_color": "#111827",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        ],
    }, headers=_NO_CACHE)


@app.get("/icon-192.png")
def icon_192():
    return Response(_icon(192), media_type="image/png")


@app.get("/icon-512.png")
def icon_512():
    return Response(_icon(512), media_type="image/png")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers=_NO_CACHE)


# Registered last so every API route above wins the match.
@app.get("/{path:path}")
def static_files(path: str):
    # Don't let the SPA fallback swallow a mistyped API call into an HTML 200.
    if path.startswith(("api/", "health")):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    p = (STATIC / path).resolve()
    if str(p).startswith(str(STATIC.resolve())) and p.is_file():
        return FileResponse(p, headers=_NO_CACHE if _revalidate(path) else None)

    # SPA deep links fall back to the shell.
    return FileResponse(STATIC / "index.html", headers=_NO_CACHE)


if __name__ == "__main__":
    have_tls = os.path.exists(TLS_CERT) and os.path.exists(TLS_KEY)
    scheme = "https" if have_tls else "http"
    print(f"ai-hunter {scheme.upper()} on :{PORT}  (static: {STATIC})")
    print(f"  LLM: {os.environ.get('LLM_BASE_URL', 'http://127.0.0.1:30087/v1')}")
    uvicorn.run(
        app, host="0.0.0.0", port=PORT,
        ssl_certfile=TLS_CERT if have_tls else None,
        ssl_keyfile=TLS_KEY if have_tls else None,
    )

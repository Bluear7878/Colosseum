from __future__ import annotations

import logging
import time
import traceback
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from colosseum.api.routes import router

# ── Logging setup ──
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("colosseum")

WEB_DIR = Path(__file__).resolve().parent / "web"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status, duration, and full traceback on errors."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        method = request.method
        path = request.url.path

        # Log request body for POST/PUT (non-static)
        body_text = ""
        if method in ("POST", "PUT", "PATCH") and not path.startswith("/static"):
            try:
                raw = await request.body()
                body_text = raw.decode("utf-8", errors="replace")[:2000]
            except Exception:
                body_text = "<unreadable>"

        logger.info(">>> %s %s %s", method, path, f"body={body_text[:200]}..." if len(body_text) > 200 else f"body={body_text}" if body_text else "")

        try:
            response = await call_next(request)
        except Exception:
            duration = (time.perf_counter() - start) * 1000
            logger.error(
                "<<< %s %s → UNHANDLED EXCEPTION (%.0fms)\n%s",
                method, path, duration, traceback.format_exc(),
            )
            raise

        duration = (time.perf_counter() - start) * 1000
        status = response.status_code

        if status >= 400:
            logger.warning("<<< %s %s → %d (%.0fms)", method, path, status, duration)
        else:
            logger.info("<<< %s %s → %d (%.0fms)", method, path, status, duration)

        # No-cache for static assets
        if path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

        return response


import asyncio
import threading
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Run model probing in a background thread at server startup."""
    from colosseum.cli import probe_all_models

    thread = threading.Thread(target=probe_all_models, daemon=True)
    thread.start()
    logger.info("Model probe launched in background thread")
    yield
    logger.info("Server shutting down")


app = FastAPI(title="Colosseum", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)
app.include_router(router)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(
        WEB_DIR / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def run() -> None:
    uvicorn.run("colosseum.main:app", host="127.0.0.1", port=8000, reload=False)

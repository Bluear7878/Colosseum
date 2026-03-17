from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from contextlib import asynccontextmanager
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
        logger.info(">>> %s %s", method, path)

        try:
            response = await call_next(request)
        except Exception:
            duration = (time.perf_counter() - start) * 1000
            logger.error(
                "<<< %s %s → UNHANDLED EXCEPTION (%.0fms)\n%s",
                method,
                path,
                duration,
                traceback.format_exc(),
            )
            raise

        duration = (time.perf_counter() - start) * 1000
        status = response.status_code

        if status == 422 and path.startswith("/runs"):
            body = b""
            async for chunk in response.body_iterator:
                body += chunk if isinstance(chunk, bytes) else chunk.encode()
            logger.warning(
                "<<< %s %s → 422 (%.0fms) VALIDATION ERROR: %s",
                method, path, duration, body.decode("utf-8", errors="replace")
            )
            from starlette.responses import Response as _Resp
            return _Resp(content=body, status_code=422, media_type="application/json")
        elif status >= 400:
            logger.warning("<<< %s %s → %d (%.0fms)", method, path, status, duration)
        else:
            logger.info("<<< %s %s → %d (%.0fms)", method, path, status, duration)

        # No-cache for static assets
        if path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"

        return response


def _probe_models_background() -> None:
    try:
        from colosseum.cli import probe_all_models

        probe_all_models()
    except Exception:
        logger.exception("Background model probe failed")


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Launch model probing without blocking request startup."""
    if os.environ.get("COLOSSEUM_DISABLE_STARTUP_PROBE") != "1":
        thread = threading.Thread(target=_probe_models_background, daemon=True)
        thread.start()
        logger.info("Model probe launched in background thread")
    yield
    logger.info("Server shutting down")


def _assert_web_assets_exist() -> None:
    required_files = (
        WEB_DIR / "index.html",
        WEB_DIR / "report.html",
        WEB_DIR / "app.js",
        WEB_DIR / "styles.css",
    )
    missing = [path.name for path in required_files if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing web assets: {', '.join(missing)}")


def create_app() -> FastAPI:
    """Create the FastAPI application with all routes and static assets mounted."""
    _assert_web_assets_exist()
    application = FastAPI(title="Colosseum", version="0.1.0", lifespan=lifespan)
    application.add_middleware(RequestLoggingMiddleware)
    application.include_router(router)
    application.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    application.add_api_route("/", index, include_in_schema=False)
    application.add_api_route("/reports/{run_id}", report_page, include_in_schema=False)
    return application


async def index() -> FileResponse:
    return FileResponse(
        WEB_DIR / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


async def report_page(run_id: str) -> FileResponse:
    return FileResponse(
        WEB_DIR / "report.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


app = create_app()


def run() -> None:
    uvicorn.run("colosseum.main:app", host="127.0.0.1", port=8000, reload=False)

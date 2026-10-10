import asyncio
import logging
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware

from classlop.dashboard import auth, home, overview
from classlop.shared import db, search, storage
from classlop.shared.settings import get_settings

log = logging.getLogger(__name__)

# The Angular build, copied here by the Dockerfile; absent when running from source.
FRONTEND = Path(__file__).resolve().parents[3] / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(title="Classlop")
    key = get_settings().session_key
    app.add_middleware(
        SessionMiddleware,
        secret_key=key.get_secret_value() if key else secrets.token_urlsafe(32),
        session_cookie="classlop_session",
        same_site="lax",
        https_only=True,
    )
    app.include_router(auth.router)
    app.include_router(home.router)
    app.include_router(overview.router)

    @app.get("/healthz")
    async def healthz(response: Response) -> dict[str, str]:
        checks = {
            "postgres": db.ping(),
            "opensearch": search.ping(),
            "s3": asyncio.to_thread(storage.ping),
        }
        results = {}
        for name, check in checks.items():
            try:
                await asyncio.wait_for(check, timeout=5)
                results[name] = "ok"
            except Exception:
                log.exception("healthz: %s unreachable", name)
                results[name] = "down"
        if "down" in results.values():
            response.status_code = 503
        return results

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> FileResponse:
        if path.startswith(("api/", "auth/")) or not FRONTEND.is_dir():
            raise HTTPException(404)
        file = (FRONTEND / path).resolve()
        if path and file.is_file() and file.is_relative_to(FRONTEND):
            return FileResponse(file)
        return FileResponse(FRONTEND / "index.html")

    return app

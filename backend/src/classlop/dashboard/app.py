import asyncio
import logging

from fastapi import FastAPI, Response

from classlop.shared import db, search, storage

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="Classlop")

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

    return app
